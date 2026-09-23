"""Private local user context used for personalization."""

from __future__ import annotations

def private_profile_summary() -> str:
    try:
        from core.memory import PreferenceStore
        store = PreferenceStore()
        facts = store.data.get("user_facts", {})
        name = facts.get("name", "the user")
        project = facts.get("current_project", "none currently specified")
        
        interests = [topic for topic, conf in store.top_interests(5)]
        interests_str = ", ".join(interests) if interests else "not specified yet"
        
        return (
            f"The user\'s name is {name}. "
            f"Top interests include: {interests_str}. "
            f"Current primary project: {project}. "
            f"Communication preference: natural conversation, clear explanations, practical examples, technical depth when requested."
        )
    except Exception as e:
        return "The user is Aayush Bhatta. Communication preference: natural conversation."
