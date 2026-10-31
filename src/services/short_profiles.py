"""Editorial starting points, not platform algorithm requirements."""

PROFILES = {
    "vk": {
        "promo_seconds": [20, 35],
        "excerpt_seconds": [30, 54],
        "words": "45–70",
        "motion": "guided",
        "direction": "Рабочая ситуация → конкретное действие → показанный результат. "
        "Аудитория: специалисты и предприниматели. Спокойная точная подача, короткие шаги.",
    },
    "reels": {
        "promo_seconds": [12, 25],
        "excerpt_seconds": [20, 45],
        "words": "28–48",
        "motion": "expressive",
        "direction": "Узнаваемая проблема → один выразительный пример → одна полезная мысль. "
        "Короткие разговорные фразы. Первое предложение сразу раскрывает проблему.",
    },
    "shorts": {
        "promo_seconds": [20, 40],
        "excerpt_seconds": [30, 54],
        "words": "45–80",
        "motion": "explain",
        "direction": "Конкретный вопрос → законченная небольшая демонстрация → ответ. "
        "Дай полезный факт из источника, а не только обещание посмотреть урок.",
    },
}


def profile_prompt(platform, kind):
    if platform is None:
        return ""
    p = PROFILES[platform]
    low, high = p[f"{kind}_seconds"]
    return (
        f"\nПрофиль {platform}: {p['direction']} Целевой хронометраж {low}–{high} секунд. "
        f"Для озвучки ориентир {p['words']} слов при темпе 1,2×. "
        "Это ориентир: не добавляй вымышленные факты ради длины. "
        "Сохраняй логические паузы. Разбей текст на короткие смысловые реплики. "
        "Не придумывай место публикации урока: используй только переданный CTA."
    )
