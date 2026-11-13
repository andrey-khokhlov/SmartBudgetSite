"""Localized FAQ presentation inputs; only ready groups are rendered."""

FAQ_GROUPS = (
    {
        "id": "about-smartbudget",
        "title_key": "faq_about_title",
        "questions": [
            {"question_key": "faq_about_q1", "body": [{"text_key": "faq_about_a1_1"}]},
            {
                "question_key": "faq_about_q2",
                "body": [
                    {"text_key": "faq_about_a2_1"},
                    {"text_key": "faq_about_a2_2"},
                    {"text_key": "faq_about_a2_3"},
                ],
            },
            {
                "question_key": "faq_about_q3",
                "body": [
                    {"text_key": "faq_about_a3_1"},
                    {"text_key": "faq_about_a3_2"},
                ],
            },
            {
                "question_key": "faq_about_q4",
                "body": [
                    {"text_key": "faq_about_a4_1"},
                    {"text_key": "faq_about_a4_2"},
                ],
            },
        ],
    },
    {
        "id": "system-requirements",
        "title_key": "faq_before_title",
        "questions": [
            {
                "id": "system-requirements-question",
                "question_key": "faq_before_q1",
                "body": [
                    {"text_key": "faq_before_a1_1"},
                    {"text_key": "faq_architectures"},
                    {"text_key": "faq_before_a1_2"},
                    {"text_key": "faq_before_a1_3"},
                    {"text_key": "faq_before_a1_4"},
                ],
            },
            {
                "question_key": "faq_before_q2",
                "body": [
                    {"text_key": "faq_before_a2_1"},
                    {"text_key": "faq_before_a2_2"},
                ],
            },
            {
                "question_key": "faq_before_q3",
                "body": [
                    {"text_key": "faq_before_a3_1"},
                    {"text_key": "faq_before_a3_2"},
                ],
            },
            {
                "question_key": "faq_before_q4",
                "body": [
                    {"text_key": "faq_before_a4_1"},
                    {"text_key": "faq_before_a4_2"},
                ],
            },
            {
                "question_key": "faq_before_q5",
                "body": [
                    {"text_key": "faq_before_a5_1"},
                    {"text_key": "faq_before_a5_2"},
                ],
            },
            {
                "question_key": "faq_before_q6",
                "body": [
                    {"text_key": "faq_before_a6_1"},
                    {"text_key": "faq_before_a6_2"},
                    {"text_key": "faq_before_a6_3"},
                    {"text_key": "faq_before_a6_4"},
                    {"text_key": "faq_before_a6_5"},
                    {
                        "text_key": "faq_before_a6_6",
                        "url": "https://learn.microsoft.com/en-us/office/vba/library-reference/concepts/getting-started-with-vba-in-office/",
                    },
                    {
                        "text_key": "faq_before_a6_7",
                        "url": "https://support.microsoft.com/en-us/office/security-privacy/enable-or-disable-activex-settings-in-office-files",
                    },
                ],
            },
            {
                "question_key": "faq_before_q7",
                "body": [
                    {"text_key": "faq_before_a7_1"},
                    {"text_key": "faq_before_a7_2"},
                    {"text_key": "faq_before_a7_3"},
                    {
                        "text_key": "faq_before_a7_4",
                        "url": "https://support.microsoft.com/en-us/office/vba/enable-or-disable-macros-in-microsoft-365-files",
                    },
                    {
                        "text_key": "faq_before_a7_5",
                        "url": "https://support.microsoft.com/en-us/office/security-privacy/enable-or-disable-activex-settings-in-office-files",
                    },
                    {
                        "text_key": "faq_before_a7_6",
                        "url": "https://support.microsoft.com/en-us/office/vba/activex-controls-are-disabled-by-default-in-microsoft-365-and-office-2024",
                    },
                    {"text_key": "faq_activex_check"},
                    {"text_key": "faq_activex_manual"},
                    {"text_key": "faq_activex_path"},
                    {"text_key": "faq_activex_setting"},
                    {"text_key": "faq_activex_restart"},
                    {"text_key": "faq_before_a7_7"},
                ],
            },
        ],
    },
    {
        "id": "purchase-and-delivery",
        "title_key": "faq_purchase_title",
        "questions": [
            {
                "question_key": f"faq_purchase_q{number}",
                "body": [
                    {
                        "text_key": f"faq_purchase_a{number}_{paragraph}",
                        "support_links": (number, paragraph) == (7, 2),
                    }
                    for paragraph in range(1, paragraph_count + 1)
                ],
            }
            for number, paragraph_count in enumerate((3, 2, 2, 2, 2, 3, 3), start=1)
        ],
    },
)
