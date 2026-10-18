"""Suggest tags + unit for a post (fast sync call). Owner: Mogith."""


async def tag_post(title: str, body: str) -> dict[str, object]:
    """Placeholder used by POST /sync/tag-post."""
    # TODO(Mogith): call the LLM with a versioned prompt and return PostTags.
    return {"tags": [], "unit_number": None}


# TODO(Mogith):
#   - get_llm().generate_json(prompt, PostTags) (add a prompt community/auto_tag.v1.j2)
