from django.utils.text import slugify


def unique_slug(model, name):
    """`name` slugified, with -2, -3… appended until no other row has it."""
    max_length = model._meta.get_field('slug').max_length
    base = slugify(name)[:max_length - 4].strip('-') or model._meta.model_name
    slug, n = base, 2
    while model.objects.filter(slug=slug).exists():
        slug, n = f'{base}-{n}', n + 1
    return slug
