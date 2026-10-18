"""Generate an illustration image and store it. Owner: Mogith."""


async def create_illustration(prompt: str) -> str:
    """Return the storage path of the generated image."""
    # TODO(Mogith): implement with providers.get_image_generator() + providers.get_storage().
    raise NotImplementedError


# TODO(Mogith):
#   - png = await get_image_generator().generate_image(prompt)
#   - path = await get_storage().save(f'visuals/{uuid}.png', png, 'image/png')
