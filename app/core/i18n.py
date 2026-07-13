from __future__ import annotations

from typing import Final
from fastapi import Request
from starlette.responses import Response

SUPPORTED_LANGS: Final[set[str]] = {"en", "ru"}
DEFAULT_LANG: Final[str] = "en"
COOKIE_NAME: Final[str] = "sb_lang"


TRANSLATIONS: Final[dict[str, dict[str, str]]] = {
    "en": {
        "brand_name": "Andrey Khokhlov",
        "nav_about": "About",
        "nav_products": "Products",
        "about_h1": "About me",
        "products_h1": "Products",
        "products_subtitle": "Thoughtfully designed products to plan, control, and improve your personal finances.",
        "about_p": (
            "I help turn data and technology into clear, practical solutions "
            "for both life and business. My goal is not just to build reports "
            "or write code, but to simplify processes, eliminate manual work, "
            "and give people a sense of control over their systems and numbers."
        ),

        "about_p2": (
            "I started my career in finance (ex-EY, ACCA/FCCA), and over time "
            "moved deeper into analytics, automation, and development. Today "
            "I work as a BI developer, combining SQL, Power BI, Tableau, Python, "
            "and Excel/VBA with a strong focus on performance and real-world value."
        ),

        "about_p3": (
            "I am also passionate about automating everyday life — smart home "
            "systems, sensors, scenarios, and Home Assistant. I like systems "
            "that work quietly, logically, and without constant manual control. "
            "The same principles guide my professional work."
        ),

        "about_b1": "BI developer with strong finance background (ex-EY, ACCA/FCCA).",
        "about_b2": "SQL Server, Power BI, Tableau — performance-focused approach.",
        "about_b3": "Building SmartBudget: Excel + VBA product with a companion web app.",

        "footer_copy": "Andrey Khokhlov",
        "link_tg_url": "https://t.me/NebulaMaverick?start=site",
        "link_wa_url": "https://wa.me/79268272465",
        "link_fb_url": "https://facebook.com/andrey.khokhlov.2025",
        "link_vk_url": "https://vk.com/id7384755",
        "link_email_url": "mailto:khokhlov.a.a@gmail.com",
        "link_li_url": "https://www.linkedin.com/in/andrey-khokhlov-acca-25315816a",

        "features_h2": "What I do",
        "feature_1_h": "Analytics & BI",
        "feature_1_p": "Designing efficient data models, dashboards, and reports that answer real business questions.",
        "feature_2_h": "Automation",
        "feature_2_p": "Automating finance and data workflows using Python, SQL, and Excel/VBA.",
        "feature_3_h": "Products",
        "feature_3_p": "Building practical tools like SmartBudget that people actually use.",

        "product_smartbudget_title": "SmartBudget",
        "product_smartbudget_subtitle": "An Excel-based personal budget: plan the year, track actuals, and spot cash gaps before they happen.",

        "product_smartbudget_h1": "Guided, step-by-step budget planning with built-in tips",
        "product_smartbudget_h2": "Plan vs Actual control to catch overspending early",
        "product_smartbudget_h3": "Utilities micro-budget: plan + actual + payment checklist",
        "product_smartbudget_h4": "Credit card cash-gap handling with a clear payoff plan",
        "product_smartbudget_h5": "Personal projects as sub-budgets (trips, goals, big plans)",
        "product_smartbudget_h6": "Built-in analytics: charts and detailed variance view",

        "product_cta_buy": "Learn more",

        "sb_lp_subtitle": "Plan the year, track actuals, and spot cash gaps before they happen.",

        "sb_lp_cta_primary": "Learn more",
        "sb_lp_cta_secondary": "See screenshots",

        "sb_lp_b1": "Detect cash gaps months in advance",
        "sb_lp_b2": "Plan vs Actual with variance tracking",
        "sb_lp_b3": "Microbudgets for utilities and personal projects",

        "sb_lp_buy_h2": "Get SmartBudget",
        "sb_lp_buy_p": "Purchase and download the latest version.",

        "sb_shot_1": "Plan & cashflow overview",
        "sb_shot_2": "Plan vs Actual (variance)",
        "sb_shot_3": "Utilities micro-budget",

# --- SmartBudget landing (EN) ---
        "sb_landing_title": "Plan, track, and understand your money — in one Excel file",
        "sb_landing_type": "A personal budgeting system in Excel",
        "sb_landing_lead": "SmartBudget gives you predictability in your personal finances: you understand how much money you have each month, avoid unexpected expenses, and confidently plan your future.",

        "sb_landing_case_home": "Planning a major goal — such as buying a home — and want to manage your money consciously",
        "sb_landing_case_job": "Building a financial safety cushion and want to feel confident about the future",
        "sb_landing_case_paycheck": "Want to understand where your money goes and keep your budget under control",
        "sb_landing_case_freelance": "Have multiple income sources and want to bring structure to your finances",

        "sb_landing_cta_primary": "View product",
        "sb_landing_cta_consult": "Paid консультация в Telegram",
        "sb_landing_note": "Works locally in Excel — no subscriptions, no data sharing.",

        "sb_nav_title": "Everything important — one click away",
        "sb_nav_p1": "When a budget grows, searching for the right sheet steals focus and time.",
        "sb_nav_p2": "A single navigation panel gives instant access to Plan, Fact, Comparison, Utilities, and more — without extra clicks.",
        "sb_nav_alt": "SmartBudget navigation panel",

        "sb_inputs_title": "All key settings in one place",
        "sb_inputs_p1": "Budget setup is often scattered: limits, accounts, cards, currencies — easy to miss something.",
        "sb_inputs_p2": "The Inputs sheet keeps core parameters together, so the budget starts from a clean and consistent base.",
        "sb_inputs_alt": "SmartBudget inputs sheet",

        "sb_plan_title": "A budget model, not a random list of expenses",
        "sb_plan_p1": "Simple spreadsheets mix everything together, and monthly results become a surprise.",
        "sb_plan_p2": "The Plan sheet structures cash flows so you can see the outcome of each month and adjust early.",
        "sb_plan_alt": "SmartBudget plan sheet",

        "sb_savings_viz_title": "See progress, not just numbers",
        "sb_savings_viz_p1": "Tables are hard to read at a glance — growth gets lost in rows and columns.",
        "sb_savings_viz_p2": "Clear charts show end-of-month balances and savings structure across the year.",
        "sb_savings_viz_alt": "Savings charts",

        "sb_fact_title": "Spot cash gaps before they hurt",
        "sb_fact_p1": "Real life differs from the plan — unexpected expenses show up and create stress.",
        "sb_fact_p2": "Fact mirrors Plan, so deviations are immediately visible and you can act in advance.",
        "sb_fact_alt": "SmartBudget fact sheet",

        "sb_utilities_title": "Never forget an important bill",
        "sb_utilities_p1": "Utilities come from different providers and at different times — it’s easy to miss one.",
        "sb_utilities_p2": "Track planned vs paid bills by month and always know what is already covered.",
        "sb_utilities_alt": "Utilities payments table",

        "sb_compare_title": "Know exactly where the budget deviates",
        "sb_compare_p1": "A monthly total may look fine, while the real reasons stay hidden.",
        "sb_compare_p2": "Comparison provides line-by-line plan vs fact with absolute and percent variance for each month.",
        "sb_compare_alt": "Plan vs fact comparison table",

        "sb_consult_title": "Need help setting it up for your life?",
        "sb_consult_p": "I offer paid 1:1 консультации: setup, workflow, and interpreting results — via Telegram.",
        "sb_consult_cta": "Message me on Telegram",

        "sb_landing_cta_buy": "Buy SmartBudget",
        "sb_final_cta_title": "Ready to take control of your budget?",

        "footer_faq": "FAQ",
        "footer_feedback": "Feedback",

        "faq_title": "FAQ",
        "faq_intro": "Answers to common questions about SmartBudget, file setup, and working with macros.",

        "faq_q1": "What is SmartBudget?",
        "faq_a1": "SmartBudget is an Excel-based personal budgeting file designed to help you plan, control, and compare your budget against actual results. It helps you track monthly balances and understand your financial picture more clearly.",

        "faq_q2": "Do I need Microsoft Excel to use it?",
        "faq_a2": "Yes. SmartBudget is built for Microsoft Excel with macro support. Excel Online and alternative spreadsheet apps may not support all features.",

        "faq_q3": "Is it safe to enable macros?",
        "faq_a3": "Yes, if the file comes from a trusted source. In SmartBudget, macros are used for interface automation, navigation, and supporting functions inside the workbook.",

        "faq_q4": "Can I use SmartBudget if my income is irregular?",
        "faq_a4": "Yes. SmartBudget is especially useful when income and expenses vary from month to month, because it helps you see future cash gaps and plan your balances in advance.",

        "faq_q5": "What should I do if the file does not open or macros are blocked?",
        "faq_a5": "In that case, use the feedback page and describe the issue. I can help you check Excel settings and explain how to open the file correctly.",

        "sb_landing_faq_link": "Frequently asked questions",
        "sb_landing_reviews_link": "User reviews",

        "feedback_title": "Feedback",
        "feedback_intro": "Use this form to send feedback, report a bug, or ask a question about SmartBudget.",
        "feedback_type_label": "Message type",

        "feedback_type_site_issue": "Website issue",
        "feedback_type_general_question": "General question",
        "feedback_type_product_feedback": "Product feedback or question",

        "feedback_name_label": "Name",
        "feedback_email_label": "Email",
        "feedback_subject_label": "Subject",
        "feedback_message_label": "Message",
        "feedback_submit": "Send",

        "feedback_email_hint": "For product feedback and questions, please provide the email used during purchase — this is required for verification.",

        "feedback_contact_email_label": "Contact email",
        "feedback_contact_email_hint": "Optional. Enter it if you would like to receive a reply to your message.",

        "feedback_purchase_label": "Product",
        "feedback_purchase_placeholder": "Select the product you want to leave feedback for",

        "feedback_checking_purchase": "Checking purchase...",
        "feedback_purchase_confirmed": "Purchase confirmed",
        "feedback_no_purchase_found": "No purchase found",
        "feedback_purchase_check_failed": "Could not verify purchase right now",
        "feedback_product_fallback": "Product",
        "feedback_sending": "Sending...",
        "feedback_sent_success_prefix": "Sent successfully. Message ID:",
        "feedback_send_failed": "Failed to send. Please try again.",
        "feedback_attachments_label": "Attach files",
        "feedback_attachments_hint": "You can upload screenshots or PDF files (up to 20 MB each, max 5 files)",

        "feedback_dropzone_title": "Drag & drop files here or click to select",
        "feedback_dropzone_hint": "Supported: PNG, JPG, WEBP, PDF",
        "feedback_dropzone_no_files": "No files selected",
        "feedback_dropzone_button": "Choose files",

        "reviews_title": "Reviews",
        "reviews_subtitle": "Public product reviews will appear here.",

        "reviews_empty": "There are no published reviews yet.",
        "reviews_from_label": "From",
        "reviews_reply_label": "Reply",
        "reviews_anonymous": "Anonymous",
        "reviews_no_subject": "No subject",

        "reviews_published_label": "Published",

        "checkout.title": "Checkout",
        "checkout.product": "Product",
        "checkout.edition": "Edition",
        "checkout.total": "Total",
        "checkout.pay_sbp": "Pay via SBP",
        "checkout.pay_ru_card": "Russian card / YooMoney / SberPay / T-Pay",
        "checkout.pay_international_card": "Pay with international card",
        "checkout.pay_crypto": "Pay with cryptocurrency",
        "checkout.package": "Package",
        "checkout.consultation": "Personal consultation",
        "checkout.included": "Added",
        "checkout.price_product": "Product price",

        "product_buy_title": "Select your SmartBudget version",
        "product_buy_subtitle": "Compare available options and continue to checkout.",
        "product_buy_edition": "Edition",
        "product_buy_file_version": "File version",
        "product_buy_price_not_configured": "Price is not configured",
        "product_buy_cta": "Continue to checkout",
        "product_buy_add_consultation": "Add a personal SmartBudget setup consultation",
        "product_buy_addon_special_price": "Special price with SmartBudget",

        "product.package_ru_hint": "Russian version of the product. Payments in RUB with local payment methods.",
        "product.package_int_hint": "English version of the product. Payments in EUR with international cards.",
        "product.recommended": "Recommended",

        "consultation_booking_title": "Book your consultation",
        "consultation_booking_intro": (
                "Your consultation access is active. "
                "Please use the button below to schedule your session."
            ),
        "consultation_booking_status": "Status",
        "consultation_booking_expires_at": "Booking access expires at",
        "consultation_book_button": "Schedule consultation",
        "consultation_booking_unavailable": (
                "Consultation booking is temporarily unavailable. "
                "Please contact support."
            ),

        "consultation_booking_security_note": "This link is personal and must not be shared.",

        "download_title": "Secure download",
        "download_kicker": "Protected download",
        "download_intro": "Review the release details below, then generate your secure temporary download link.",
        "download_version": "Version",
        "download_release_date": "Release date",
        "download_filename": "Filename",
        "download_file_size": "File size",
        "download_sha256": "SHA-256",
        "download_expires_at": "Access expires at",
        "download_remaining_attempts": "Remaining attempts",
        "download_support_reference": "Support reference",
        "download_button": "Download",
        "download_secure_note": "A secure temporary link is generated only after you click Download and remains valid for {minutes} minutes.",
        "download_error_title": "Download unavailable",
        "download_error_unknown": "This download link is unknown or invalid.",
        "download_error_expired": "This download link has expired.",
        "download_error_cancelled": "This download access has been cancelled.",
        "download_error_completed": "This download has already been completed.",
        "download_error_attempt_limit": "The maximum number of download attempts has been reached.",
        "download_error_missing_release": "The purchased release is currently unavailable.",
        "download_error_unavailable": "The download service is temporarily unavailable. Please try again later.",
        "download_error_support_prefix": "Contact support through the ",
        "download_feedback_link": "Feedback Form",
        "download_error_support_suffix": " and provide reference code {reference}.",

    },
    "ru": {
        "brand_name": "Андрей Хохлов",
        "nav_about": "Обо мне",
        "nav_products": "Продукты",
        "about_h1": "Обо мне",
        "products_h1": "Продукты",
        "products_subtitle": "Продуманные продукты для планирования, контроля и улучшения личных финансов.",

        "about_p": (
            "Я помогаю превращать данные и технологии в понятные и практичные решения "
            "для жизни и бизнеса. Для меня важно не просто сделать отчёт или написать код, "
            "а упростить процессы, убрать ручной труд и дать человеку ощущение контроля "
            "над цифрами и системами."
        ),

        "about_p2": (
            "По образованию и опыту я финансист (ex-EY, ACCA/FCCA), но со временем "
            "ушёл глубже в аналитику, автоматизацию и разработку. Сейчас я работаю "
            "как BI-разработчик, сочетая SQL, Power BI, Tableau, Python и Excel/VBA "
            "с фокусом на производительность и практическую пользу."
        ),

        "about_p3": (
            "Отдельная часть моих интересов — автоматизация повседневной жизни: "
            "умный дом, датчики, сценарии и Home Assistant. Мне нравятся системы, "
            "которые работают тихо, логично и без постоянного ручного вмешательства. "
            "Тот же принцип я применяю и в профессиональной работе."
        ),
        "about_b1": "BI-разработчик с сильной финансовой базой (ex-EY, ACCA/FCCA).",
        "about_b2": "SQL Server, Power BI, Tableau — фокус на производительности.",
        "about_b3": "Делаю SmartBudget: продукт на Excel + VBA и сайт-компаньон.",

        "footer_copy": "Andrey Khokhlov",
        "link_tg_url": "https://t.me/NebulaMaverick?start=site",
        "link_wa_url": "https://wa.me/79268272465",
        "link_fb_url": "https://facebook.com/andrey.khokhlov.2025",
        "link_vk_url": "https://vk.com/id7384755",
        "link_email_url": "mailto:khokhlov.a.a@gmail.com",
        "link_li_url": "https://www.linkedin.com/in/andrey-khokhlov-acca-25315816a",

        "features_h2": "Чем я занимаюсь",
        "feature_1_h": "Аналитика и BI",
        "feature_1_p": "Проектирование моделей данных, дашбордов и отчетов для реальных бизнес-задач.",
        "feature_2_h": "Автоматизация",
        "feature_2_p": "Автоматизация финансовых и аналитических процессов на Python, SQL и Excel/VBA.",
        "feature_3_h": "Продукты",
        "feature_3_p": "Создание практичных продуктов, таких как SmartBudget.",

        "product_smartbudget_title": "SmartBudget",
        "product_smartbudget_subtitle": "Личный бюджет в Excel: планируй на год вперёд, контролируй факт, предотвращай кассовые разрывы.",

        "product_smartbudget_h1": "Пошаговое планирование бюджета (walkthrough с подсказками)",
        "product_smartbudget_h2": "План vs Факт: быстро видно перерасход и отклонения",
        "product_smartbudget_h3": "Коммуналка как микробюджет: план + факт + контроль оплат",
        "product_smartbudget_h4": "Кредитные карты: закрывай разрывы и планируй погашение",
        "product_smartbudget_h5": "Личные проекты: подбюджеты для поездок/ремонта/целей",
        "product_smartbudget_h6": "Встроенная аналитика: графики и детальный план-факт",

        "product_cta_buy": "Подробнее",

        "sb_lp_subtitle": "Планирование года, контроль факта и раннее выявление кассовых разрывов.",

        "sb_lp_cta_primary": "Подробнее",
        "sb_lp_cta_secondary": "Скриншоты",

        "sb_lp_b1": "Видно кассовые разрывы за месяцы вперёд",
        "sb_lp_b2": "План vs Факт с отклонениями и контролем перерасхода",
        "sb_lp_b3": "Микробюджеты: коммуналка и личные проекты",

        "sb_lp_buy_h2": "Получить SmartBudget",
        "sb_lp_buy_p": "Оплата и скачивание последней версии.",

        "sb_shot_1": "План и денежные потоки",
        "sb_shot_2": "План vs Факт (отклонения)",
        "sb_shot_3": "Микробюджет: коммуналка",

# --- SmartBudget landing (RU) ---
        "sb_landing_title": "Планируйте и контролируйте личный бюджет — в одном Excel-файле",
        "sb_landing_type": "Персональная система управления бюджетом в Excel",
        "sb_landing_lead": "SmartBudget даёт предсказуемость в личных финансах: вы понимаете, сколько денег у вас есть каждый месяц, избегаете неожиданных расходов и уверенно планируете будущее.",

        "sb_landing_case_home": "Планируете крупную цель — например, покупку жилья — и хотите управлять деньгами осознанно",
        "sb_landing_case_job": "Создаёте финансовую подушку и хотите чувствовать уверенность в будущем",
        "sb_landing_case_paycheck": "Хотите понимать, куда уходят деньги, и держать бюджет под контролем",
        "sb_landing_case_freelance": "Получаете доход из разных источников и хотите навести порядок в финансах",

        "sb_landing_cta_primary": "Смотреть продукт",
        "sb_landing_cta_consult": "Платная консультация в Telegram",
        "sb_landing_note": "Работает локально в Excel — без подписок и передачи данных.",

        "sb_nav_title": "Всё важное — в один клик",
        "sb_nav_p1": "Когда бюджет разрастается, поиск нужного раздела начинает мешать думать.",
        "sb_nav_p2": "Единая панель навигации даёт быстрый доступ к Плану, Факту, Сравнению, Коммуналке и другим разделам.",
        "sb_nav_alt": "Панель навигации SmartBudget",

        "sb_inputs_title": "Все настройки бюджета — в одном месте",
        "sb_inputs_p1": "Обычно параметры раскиданы по файлу: лимиты, счета, карты, валюты — легко что-то забыть.",
        "sb_inputs_p2": "Лист «Вводные данные» собирает базовые параметры в одной форме — бюджет начинается с чистой и понятной основы.",
        "sb_inputs_alt": "Лист «Вводные данные»",

        "sb_plan_title": "Система денежных потоков вместо хаотичной таблицы",
        "sb_plan_p1": "В обычных таблицах всё смешивается, и итог месяца становится сюрпризом.",
        "sb_plan_p2": "Лист «План» структурирует бюджет так, чтобы видеть результат каждого месяца и корректировать заранее.",
        "sb_plan_alt": "Лист «План»",

        "sb_savings_viz_title": "Видно прогресс, а не только цифры",
        "sb_savings_viz_p1": "Табличные итоги по месяцам трудно воспринимать: динамика теряется.",
        "sb_savings_viz_p2": "Графики показывают остатки на конец месяца и структуру сбережений в динамике года.",
        "sb_savings_viz_alt": "Графики сбережений",

        "sb_fact_title": "Кассовые разрывы видны заранее",
        "sb_fact_p1": "Факт почти всегда отличается от плана — внезапные траты создают стресс.",
        "sb_fact_p2": "Лист «Факт» повторяет структуру плана, поэтому отклонения сразу заметны и можно действовать заранее.",
        "sb_fact_alt": "Лист «Факт»",

        "sb_utilities_title": "Не забывайте оплачивать важные счета",
        "sb_utilities_p1": "Коммунальные счета приходят от разных поставщиков и в разное время — легко пропустить платёж.",
        "sb_utilities_p2": "Планируйте и отмечайте оплату по месяцам и всегда видите, что уже закрыто, а что требует внимания.",
        "sb_utilities_alt": "Коммунальные платежи",

        "sb_compare_title": "Постатейный план-факт контроль",
        "sb_compare_p1": "Общий итог месяца может выглядеть нормально, но причины отклонений остаются неочевидными.",
        "sb_compare_p2": "Лист «Сравнение» показывает суммы, отклонения и проценты по каждой статье в разрезе месяцев.",
        "sb_compare_alt": "Таблица сравнения План vs Факт",

        "sb_consult_title": "Нужна помощь с настройкой под вашу жизнь?",
        "sb_consult_p": "Делаю платные 1:1 консультации: настройка, процесс ведения бюджета и разбор результатов — в Telegram.",
        "sb_consult_cta": "Написать в Telegram",

        "sb_landing_cta_buy": "Купить SmartBudget",
        "sb_final_cta_title": "Готовы навести порядок в бюджете?",

        "footer_faq": "FAQ",
        "footer_feedback": "Обратная связь",

        "faq_title": "FAQ",
        "faq_intro": "Ответы на частые вопросы о SmartBudget, установке файла и работе с макросами.",

        "faq_q1": "Что такое SmartBudget?",
        "faq_a1": "SmartBudget — это Excel-файл для планирования и контроля личного бюджета. Он помогает сопоставлять план и факт, отслеживать остатки денег по месяцам и лучше понимать свою финансовую ситуацию.",

        "faq_q2": "Нужен ли Microsoft Excel для работы?",
        "faq_a2": "Да. SmartBudget работает в Microsoft Excel с поддержкой макросов. Онлайн-версии Excel и альтернативные редакторы таблиц могут не поддерживать весь функционал.",

        "faq_q3": "Безопасно ли включать макросы?",
        "faq_a3": "Да, если файл получен из надёжного источника. Макросы в SmartBudget нужны для автоматизации интерфейса, навигации и вспомогательных функций внутри файла.",

        "faq_q4": "Подойдёт ли SmartBudget, если у меня нерегулярный доход?",
        "faq_a4": "Да. SmartBudget особенно полезен в ситуациях, когда доходы и расходы меняются от месяца к месяцу, потому что помогает заранее видеть денежные разрывы и планировать остатки.",

        "faq_q5": "Что делать, если файл не открывается или макросы заблокированы?",
        "faq_a5": "В этом случае используйте страницу обратной связи и опишите проблему. Я смогу подсказать, что проверить в настройках Excel и как корректно открыть файл.",

        "sb_landing_faq_link": "Ответы на частые вопросы",
        "sb_landing_reviews_link": "Отзывы пользователей",

        "feedback_title": "Обратная связь",
        "feedback_intro": "Здесь вы можете отправить отзыв, сообщить об ошибке или задать вопрос по SmartBudget.",
        "feedback_type_label": "Тип сообщения",

        "feedback_type_site_issue": "Ошибка сайта",
        "feedback_type_general_question": "Общий вопрос",
        "feedback_type_product_feedback": "Отзыв или вопрос по продукту",

        "feedback_name_label": "Имя",
        "feedback_email_label": "Email",
        "feedback_subject_label": "Тема",
        "feedback_message_label": "Сообщение",
        "feedback_submit": "Отправить",

        "feedback_email_hint": "Для отзывов и вопросов по работе продукта укажите email, использованный при покупке — это нужно для проверки.",

        "feedback_contact_email_label": "Контактный email",
        "feedback_contact_email_hint": "Необязательно. Укажите, если хотите получить ответ по сообщению.",

        "feedback_purchase_label": "Продукт",
        "feedback_purchase_placeholder": "Выберите продукт, по которому хотите оставить отзыв",

        "feedback_checking_purchase": "Проверяем покупку...",
        "feedback_purchase_confirmed": "Покупка подтверждена",
        "feedback_no_purchase_found": "Покупка не найдена",
        "feedback_purchase_check_failed": "Не удалось проверить покупку прямо сейчас",
        "feedback_product_fallback": "Продукт",
        "feedback_sending": "Отправка...",
        "feedback_sent_success_prefix": "Отправлено. ID сообщения:",
        "feedback_send_failed": "Не удалось отправить. Попробуйте снова.",

        "feedback_attachments_label": "Прикрепить файлы",
        "feedback_attachments_hint": "Можно добавить скриншоты или PDF (до 20 МБ каждый, максимум 5 файлов)",

        "feedback_dropzone_title": "Перетащите файлы сюда или нажмите для выбора",
        "feedback_dropzone_hint": "Поддерживаются PNG, JPG, WEBP и PDF",
        "feedback_dropzone_no_files": "Файлы не выбраны",
        "feedback_dropzone_button": "Выбрать файлы",

        "reviews_title": "Отзывы",
        "reviews_subtitle": "Публичные отзывы о продукте будут отображаться здесь.",

        "reviews_empty": "Пока опубликованных отзывов нет.",
        "reviews_from_label": "Автор",
        "reviews_reply_label": "Ответ",
        "reviews_anonymous": "Анонимно",
        "reviews_no_subject": "Без темы",

        "reviews_published_label": "Опубликовано",

        "checkout.title": "Оплата",
        "checkout.product": "Продукт",
        "checkout.edition": "Версия",
        "checkout.total": "Итого",
        "checkout.pay_sbp": "Оплата через СБП",
        "checkout.pay_ru_card": "Карта РФ / ЮMoney / SberPay / T-Pay",
        "checkout.pay_international_card": "Оплата зарубежной картой",
        "checkout.pay_crypto": "Оплатить криптовалютой",
        "checkout.package": "Пакет",
        "checkout.consultation": "Личная консультация",
        "checkout.included": "Добавлена",
        "checkout.price_product": "Стоимость продукта",

        "product_buy_title": "Выберите версию SmartBudget",
        "product_buy_subtitle": "Сравните доступные варианты и перейдите к оплате подходящей версии.",
        "product_buy_edition": "Версия",
        "product_buy_file_version": "Файл",
        "product_buy_price_not_configured": "Цена не настроена",
        "product_buy_cta": "Перейти к оплате",
        "product_buy_add_consultation": "Добавить личную консультацию по настройке SmartBudget",
        "product_buy_addon_special_price": "Специальная цена при покупке",

        "product.package_ru_hint": "Версия на русском языке. Оплата в рублях и локальные платёжные методы.",
        "product.package_int_hint": "Версия на английском языке. Оплата в евро и международные карты.",
        "product.recommended": "Рекомендуем",

        "consultation_booking_title": "Запись на консультацию",
        "consultation_booking_intro": (
                "Доступ к консультации активен. "
                "Используйте кнопку ниже, чтобы выбрать удобное время."
            ),
        "consultation_booking_status": "Статус",
        "consultation_booking_expires_at": "Запись активна до",
        "consultation_book_button": "Выбрать время консультации",
        "consultation_booking_unavailable": (
                "Запись на консультацию временно недоступна. "
                "Пожалуйста, свяжитесь с поддержкой."
            ),

        "consultation_booking_security_note": "Ссылка является персональной и не подлежит передаче.",

        "download_title": "Безопасное скачивание",
        "download_kicker": "Защищённое скачивание",
        "download_intro": "Проверьте информацию о выпуске, затем создайте временную защищённую ссылку для скачивания.",
        "download_version": "Версия",
        "download_release_date": "Дата выпуска",
        "download_filename": "Имя файла",
        "download_file_size": "Размер файла",
        "download_sha256": "SHA-256",
        "download_expires_at": "Доступ действует до",
        "download_remaining_attempts": "Осталось попыток",
        "download_support_reference": "Номер для поддержки",
        "download_button": "Скачать",
        "download_secure_note": "Временная защищённая ссылка создаётся только после нажатия кнопки «Скачать» и действует {minutes} минут.",
        "download_error_title": "Скачивание недоступно",
        "download_error_unknown": "Ссылка для скачивания не найдена или недействительна.",
        "download_error_expired": "Срок действия ссылки для скачивания истёк.",
        "download_error_cancelled": "Доступ к скачиванию был отменён.",
        "download_error_completed": "Это скачивание уже было завершено.",
        "download_error_attempt_limit": "Достигнуто максимальное количество попыток скачивания.",
        "download_error_missing_release": "Приобретённый выпуск сейчас недоступен.",
        "download_error_unavailable": "Сервис скачивания временно недоступен. Пожалуйста, повторите попытку позже.",
        "download_error_support_prefix": "Обратитесь в поддержку через ",
        "download_feedback_link": "форму обратной связи",
        "download_error_support_suffix": " и сообщите код обращения {reference}.",

    },
}


def get_lang(request: Request) -> str:
    # 1) explicit query param
    q = (request.query_params.get("lang") or "").lower()
    if q in SUPPORTED_LANGS:
        return q

    # 2) cookie
    c = (request.cookies.get(COOKIE_NAME) or "").lower()
    if c in SUPPORTED_LANGS:
        return c

    return DEFAULT_LANG


def set_lang_cookie(response: Response, lang: str) -> None:
    if lang in SUPPORTED_LANGS:
        response.set_cookie(
            key=COOKIE_NAME,
            value=lang,
            max_age=60 * 60 * 24 * 365,
            samesite="lax",
            httponly=False,
        )


def t(lang: str, key: str) -> str:
    return TRANSLATIONS.get(lang, TRANSLATIONS[DEFAULT_LANG]).get(key, key)
