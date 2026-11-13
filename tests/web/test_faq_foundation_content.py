import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from app.core.i18n import TRANSLATIONS

PUBLIC_COMPATIBILITY = {
    "ru": (
        "SmartBudget 1.0 предназначен для Windows 10/11 и настольной версии Microsoft Excel для Windows начиная с Excel 2019, включая Microsoft 365.",
        "Поддерживаются 32-разрядные и 64-разрядные версии Excel. Эти требования относятся к текущей версии SmartBudget 1.0 и не являются гарантией совместимости со всеми будущими выпусками Excel.",
    ),
    "en": (
        "SmartBudget 1.0 requires Windows 10/11 and desktop Microsoft Excel for Windows 2019 or later, including Microsoft 365.",
        "Both 32-bit and 64-bit editions of Excel are supported. These requirements apply to the current SmartBudget 1.0 release and do not guarantee compatibility with every future Excel release.",
    ),
}


class FAQContent(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.in_main = False
        self.groups = []
        self.group = None
        self.question = None
        self.capture = None
        self.depth = 0
        self.title = None
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        if tag == "main":
            self.in_main = True
        if not self.in_main:
            return
        attrs = dict(attrs)
        if tag == "section":
            self.group = {**attrs, "questions": [], "links": []}
            self.groups.append(self.group)
        if tag == "details":
            self.depth += 1
            assert self.depth == 1, "FAQ accordions must not be nested"
            self.question = {**attrs, "paragraphs": []}
            self.group["questions"].append(self.question)
        if tag in {"h1", "h2", "summary", "p"}:
            self.capture = {"tag": tag, "text": ""}
        if tag == "a":
            self.group["links"].append(attrs)

    def handle_endtag(self, tag):
        if self.capture and tag == self.capture["tag"]:
            value = " ".join(self.capture["text"].split())
            if tag == "h1":
                self.title = value
            elif tag == "h2":
                self.group["title"] = value
            elif tag == "summary":
                self.question["title"] = value
            elif tag == "p" and self.question is not None:
                self.question["paragraphs"].append(value)
            self.capture = None
        if tag == "details":
            self.depth -= 1
            self.question = None
        if tag == "main":
            self.in_main = False

    def handle_data(self, text):
        if self.in_main and self.capture is not None:
            self.capture["text"] += text


def approved_section(number):
    source = Path("docs/release_uiux_requirements.md").read_text(encoding="utf-8")
    return source.split(f"#### 5.6.{number}.", 1)[1].split(
        f"#### 5.6.{number + 1}.", 1
    )[0]


def approved_questions(block, lang):
    locales = re.split(r"^##### (RU|EN)(?: — .*?)?\n", block, flags=re.MULTILINE)
    localized = dict(zip(locales[1::2], locales[2::2], strict=True))[lang.upper()]
    return [
        chunk.strip().split("\n\n")
        for chunk in re.split(r"###### \d+\. ", localized)[1:]
    ]


@pytest.mark.parametrize("lang", ["ru", "en"])
def test_faq_has_only_ready_groups_and_four_exact_overview_questions(client, lang):
    response = client.get(f"/faq?lang={lang}")
    assert response.status_code == 200
    page = FAQContent(response.text)
    assert page.title == (
        "Частые вопросы" if lang == "ru" else "Frequently Asked Questions"
    )
    assert [group["id"] for group in page.groups] == [
        "about-smartbudget",
        "system-requirements",
        "purchase-and-delivery",
    ]
    assert [group["title"] for group in page.groups] == (
        ["О SmartBudget", "Перед покупкой", "Покупка и получение продукта"]
        if lang == "ru"
        else ["About SmartBudget", "Before You Buy", "Purchase and Delivery"]
    )
    assert [len(group["questions"]) for group in page.groups] == [4, 7, 7]
    for actual, approved in zip(
        page.groups[0]["questions"],
        approved_questions(approved_section(1), lang),
        strict=True,
    ):
        assert actual["title"] == approved[0]
        assert actual["paragraphs"] == approved[1:]
    for number in range(1, 6):
        assert TRANSLATIONS[lang][f"faq_a{number}"] not in response.text
    assert page.depth == 0


@pytest.mark.parametrize("lang", ["ru", "en"])
def test_purchase_faq_matches_approved_copy_order_and_support_links(client, lang):
    page = FAQContent(client.get(f"/faq?lang={lang}").text)
    group = page.groups[2]
    assert [
        [question["title"], *question["paragraphs"]]
        for question in group["questions"]
    ] == approved_questions(approved_section(3), lang)
    assert [link["href"] for link in group["links"]] == [
        f"/feedback?lang={lang}",
        "mailto:support@neocitrix.com",
    ]


@pytest.mark.parametrize("lang", ["ru", "en"])
def test_before_buy_preserves_all_approved_questions_answers_and_microsoft_links(
    client, lang
):
    response = client.get(f"/faq?lang={lang}")
    page = FAQContent(response.text)
    questions = page.groups[1]["questions"]
    core, extra = approved_section(2).split("**Дополнительные два вопроса RU/EN:**", 1)
    for actual, approved in zip(
        questions[:5], approved_questions(core, lang), strict=True
    ):
        assert actual["title"] == approved[0]
        expected_body = approved[1:]
        if actual is questions[0]:
            expected_body[:1] = PUBLIC_COMPATIBILITY[lang]
        assert actual["paragraphs"] == expected_body
    assert " ".join(questions[0]["paragraphs"]).count("2019") == 1
    assert "faq_m365" not in TRANSLATIONS[lang]
    localized = (
        extra.split(f"##### {lang.upper()} — ", 1)[1]
        .split("##### EN — ", 1)[0]
        .split("**Источники ссылок:**", 1)[0]
        .strip()
    )
    config_title = (
        "Как разрешить выполнение VBA и ActiveX в Excel?"
        if lang == "ru"
        else "How do I enable VBA macros and ActiveX controls in Excel?"
    )
    explanation, config = localized.split("\n\n" + config_title + "\n\n", 1)
    expected_links = []
    for actual, paragraphs in [
        (questions[5], explanation.split("\n\n")),
        (questions[6], [config_title] + config.split("\n\n")),
    ]:
        assert actual["title"] == paragraphs[0]
        approved_body = []
        for paragraph in paragraphs[1:]:
            link = re.fullmatch(r"\[(.*?)\]\((https://.*?)\)", paragraph)
            if link:
                expected_links.append(link[2])
            approved_body.append(link[1] if link else paragraph)
        # R47 adds factual configuration steps without rewriting the approved answers.
        position = 0
        for paragraph in actual["paragraphs"]:
            if position < len(approved_body) and paragraph == approved_body[position]:
                position += 1
        assert position == len(approved_body)
    links = page.groups[1]["links"]
    assert [link["href"] for link in links] == expected_links
    assert len(links) == 5
    for link in links:
        assert urlsplit(link["href"]).hostname in {
            "learn.microsoft.com",
            "support.microsoft.com",
        }
        assert link["target"] == "_blank"
        assert "noopener" in link["rel"].split()


@pytest.mark.parametrize("lang", ["ru", "en"])
def test_public_compatibility_and_manual_activex_guidance_exclude_internal_evidence(
    client, lang
):
    response = client.get(f"/faq?lang={lang}")
    page = FAQContent(response.text)
    questions = page.groups[1]["questions"]
    text = " ".join(p for question in questions for p in question["paragraphs"])
    for required in (
        "Windows 10/11",
        "Microsoft 365",
        "VBA",
        "ActiveX",
        "Google Sheets",
        "Safe Mode",
    ):
        assert required in text
    if lang == "en":
        for required in (
            "Excel for Mac and Excel for the web are not supported",
            "browser-based spreadsheet editors are not supported",
            "company-managed computers",
            "does not automatically change Office/Excel security settings",
            "change it manually",
            "must restart Excel",
            "On the next launch",
            PUBLIC_COMPATIBILITY["en"][0],
            "Both 32-bit and 64-bit editions of Excel are supported.",
            "These requirements apply to the current SmartBudget 1.0 release and do not guarantee compatibility with every future Excel release.",
            "File → Options → Trust Center → Trust Center Settings → ActiveX Settings",
            "Prompt me before enabling all controls with minimal restrictions",
        ):
            assert required in text
    else:
        for required in (
            "Excel для Mac и браузерная версия Excel не поддерживаются",
            "браузерные редакторы электронных таблиц не являются поддерживаемой средой",
            "корпоративными настройками безопасности",
            "не изменяет настройки безопасности Office/Excel автоматически",
            "меняет её вручную",
            "необходимо перезапустить Excel",
            "При следующем запуске",
            PUBLIC_COMPATIBILITY["ru"][0],
            "Поддерживаются 32-разрядные и 64-разрядные версии Excel.",
            "Эти требования относятся к текущей версии SmartBudget 1.0 и не являются гарантией совместимости со всеми будущими выпусками Excel.",
            "Файл → Параметры → Центр управления безопасностью → Параметры центра управления безопасностью → Параметры ActiveX",
            "Запрашивать разрешение перед включением всех элементов управления с минимальными ограничениями",
        ):
            assert required in text
    for forbidden in (
        "2608",
        "Click-to-Run",
        "Current Channel",
        "Practical validation",
        "has not been confirmed",
        "Практическая проверка",
        "не подтверждена",
        "Enable all controls without restrictions and without prompting",
        "Application.SendKeys",
        "without requiring the workbook to be closed",
        "Home / Professional / Personal",
    ):
        assert forbidden not in response.text
    assert 'id="system-requirements"' in response.text


@pytest.mark.parametrize("lang", ["ru", "en"])
@pytest.mark.parametrize("open_value", [None, "system-requirements", "unknown"])
def test_faq_only_opens_known_explicit_compatibility_state(client, lang, open_value):
    params = {"lang": lang}
    if open_value is not None:
        params["open"] = open_value
    page = FAQContent(client.get("/faq", params=params).text)
    questions = [question for group in page.groups for question in group["questions"]]
    opened = [question for question in questions if "open" in question]
    target = page.groups[1]["questions"][0]
    assert target["id"] == "system-requirements-question"
    assert opened == ([target] if open_value == "system-requirements" else [])
