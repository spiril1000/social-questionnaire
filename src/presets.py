"""Starting points for each questionnaire site.

A site's PRESET env var (set in its docker-compose.yml) picks one of PRESETS. On first start it
seeds /config/questions.json, and its settings are the defaults for everything on the settings
page. After that the admin panel is the place to change things; the presets are only used again
by the "Reset" buttons.

Adding a preset: add an entry to PRESETS with the settings that differ from BASE_SETTINGS and a
list of questions. Each question needs a unique "id" (answers are stored under it), a "type" and a
"label"; "required": True makes it mandatory.

Question types:
    stars   - 1-5 rating
    nps     - 0-10 "how likely"
    choice  - pick one of "options"
    matrix  - 1-5 rating for each of "rows"
    text    - free text (capped at MAX_TEXT chars); "multiline": True for a big box
    contact - preferred contact method (CONTACT_METHODS) plus a username/number field

The ids "overall", "nps", "contact" and "comment" also fill shortcut fields in the n8n webhook.
"""

MAX_TEXT = 2000

TYPES = {
    "stars": "Star rating",
    "choice": "Multiple choice",
    "matrix": "Rating grid",
    "nps": "0–10 score",
    "text": "Free text",
    "contact": "Contact details",
}

# (key, label, placeholder for the username/number field). "none" needs no details.
CONTACT_METHODS = [
    ("instagram", "Instagram", "@username"),
    ("snapchat", "Snapchat", "Snapchat username"),
    ("facebook", "Facebook", "Name or profile link"),
    ("phone", "Phone number", "+1 555 0100"),
    ("other", "Other", "Where can we find you?"),
    ("none", "Don't contact me", ""),
]

# Every setting the admin can change. New settings only need a default here (and a field
# on the settings page); existing sites pick the default up automatically.
BASE_SETTINGS = {
    "brand_name": "Acme Hospitality Group",
    "page_title": "Customer Experience Survey",
    "intro_title": "Dear valued customer",
    "intro_text": "Thank you for choosing us. We'd love to hear how we did.",
    "intro_meta": "2 minutes · awkwardness: low",
    "start_button": "Start survey",
    "thanks_title": "It's a review!",
    "thanks_text": "A member of our quality assurance team will review your response within 3–5 business days.",
    "thanks_subtext": "We hope to welcome you back soon. Terms and conditions apply.",
    "fine_print": "Responses are processed in accordance with GDPR, local regulations and good vibes. "
                  "All rights reserved, none respected.",
    "color_scheme": "flame",
    "logo": "flame",
}


def contact_question(label):
    return {"id": "contact", "type": "contact", "label": label}


PRESETS = {
    "hookup": {
        "settings": {
            "intro_text": "Thank you for choosing us for your recent hookup. We'd love to hear how we did.",
            "thanks_text": "A member of our quality assurance team will review your response within "
                           "3–5 business days, or sooner if it was a 5.",
        },
        "questions": [
            {"id": "overall", "type": "stars", "required": True,
             "label": "Overall, how satisfied were you with your experience?"},
            {"id": "source", "type": "choice", "label": "How did you hear about us?",
             "options": ["Dating app", "Bar", "Friend of a friend", "Destiny", "Prefer not to say"]},
            {"id": "amenities", "type": "matrix", "label": "Please rate the following amenities.",
             "rows": ["Conversation", "Ambience", "Breakfast offering", "Thermostat management"]},
            {"id": "nps", "type": "nps", "label": "How likely are you to recommend this service to a friend?"},
            {"id": "duration", "type": "choice", "label": "Was your stay longer or shorter than expected?",
             "options": ["Much shorter", "About right", "Overstayed welcome"]},
            {"id": "return", "type": "choice", "label": "Would you consider a return visit?",
             "options": ["Absolutely", "Possibly", "Please remove me from your mailing list"]},
            {"id": "comment", "type": "text", "multiline": True,
             "label": "Any comments for our quality assurance team?"},
            contact_question("How would you prefer our loyalty team to contact you?"),
            {"id": "name", "type": "text", "label": "Your name or nickname, for our loyalty programme (optional)."},
        ],
    },
    "ghosted": {
        "settings": {
            "brand_name": "Acme Relationship Services",
            "page_title": "Exit Interview",
            "intro_title": "We noticed you've gone quiet",
            "intro_text": "Our records show that you recently discontinued communication with us. "
                          "To help us improve, please complete this short exit interview.",
            "intro_meta": "2 minutes · closure: guaranteed",
            "start_button": "Begin exit interview",
            "thanks_title": "Closure achieved.",
            "thanks_text": "Your exit interview has been filed. We wish you all the best in your future "
                           "communication endeavours.",
            "thanks_subtext": "Our door (and DMs) remain open. No hard feelings. Mostly.",
            "color_scheme": "twilight",
            "logo": "ghost",
        },
        "questions": [
            {"id": "overall", "type": "stars", "required": True,
             "label": "How would you rate your experience before the disappearance?"},
            {"id": "reason", "type": "choice", "label": "What best describes your decision to stop replying?",
             "options": ["Lost interest", "Met someone else", "Got busy (for several weeks)",
                         "Phone fell in the ocean", "Witness protection"]},
            {"id": "communication", "type": "matrix", "label": "Please rate the following aspects of our communication.",
             "rows": ["Texting frequency", "Emoji usage", "Meme quality", "Response time"]},
            {"id": "intent", "type": "choice", "label": "Was the ghosting:",
             "options": ["Intentional", "Accidental", "I'm actually a ghost"]},
            {"id": "nps", "type": "nps", "label": "How likely are you to un-ghost us in the future?"},
            {"id": "comment", "type": "text", "multiline": True,
             "label": "Is there anything we could have done differently?"},
            contact_question("If you ever reconsider, where can we reach you?"),
        ],
    },
    "date": {
        "settings": {
            "brand_name": "Acme Dining & Romance",
            "page_title": "Post-Date Survey",
            "intro_title": "Dear valued date",
            "intro_text": "Thank you for joining us for a recent evening out. "
                          "Please take a moment to rate your experience.",
            "intro_meta": "2 minutes · butterflies: optional",
            "start_button": "Rate your date",
            "thanks_title": "Date logged!",
            "thanks_text": "Our romance department will review your feedback and get back to you "
                           "regarding a potential second date.",
            "thanks_subtext": "Reservations for a second date are subject to availability.",
            "color_scheme": "sunset",
            "logo": "wine",
        },
        "questions": [
            {"id": "overall", "type": "stars", "required": True, "label": "Overall, how would you rate the date?"},
            {"id": "chemistry", "type": "choice", "label": "How would you describe the chemistry?",
             "options": ["Fireworks", "A spark", "Static", "A chemistry exam I failed"]},
            {"id": "aspects", "type": "matrix", "label": "Please rate the following.",
             "rows": ["Conversation", "Outfit", "Choice of venue", "Sense of humour"]},
            {"id": "ending", "type": "choice", "label": "How did the evening end?",
             "options": ["Too soon", "Just right", "Should have ended earlier"]},
            {"id": "nps", "type": "nps", "label": "How likely are you to go on a second date?"},
            {"id": "comment", "type": "text", "multiline": True, "label": "Anything you'd like to add?"},
            contact_question("Where should we send the second-date invitation?"),
        ],
    },
}


def get_preset(name):
    """The preset by name, falling back to "hookup" for unknown names."""
    preset = PRESETS.get(name) or PRESETS["hookup"]
    return {"settings": {**BASE_SETTINGS, **preset["settings"]}, "questions": preset["questions"]}
