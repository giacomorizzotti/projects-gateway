from django.db import migrations, models

# The kinds that were fixed in the code until now, and whether the health checks compared the
# certificates' names on them (the server renews its own certificates).
KINDS = [
    ('home_server', 'Home server', True), ('vps', 'VPS', True), ('shared_hosting', 'Shared hosting', False),
    ('client_server', 'Client server', False), ('lan_device', 'LAN device', False),
    ('third_party', 'Third-party hosting', False),
]


def create_kinds(apps, schema_editor):
    PlatformKind = apps.get_model('catalog', 'PlatformKind')
    Platform = apps.get_model('catalog', 'Platform')
    for slug, name, renews in KINDS:
        PlatformKind.objects.create(slug=slug, name=name, renews_certificates=renews)
    # Anything else a platform holds gets a kind too, so none is left without one.
    known = {slug for slug, _, _ in KINDS}
    for slug in sorted(set(Platform.objects.values_list('kind', flat=True)) - known - {''}):
        PlatformKind.objects.create(slug=slug, name=slug)


def drop_kinds(apps, schema_editor):
    apps.get_model('catalog', 'PlatformKind').objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0007_technology_categories'),
    ]

    operations = [
        migrations.CreateModel(
            name='PlatformKind',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=60, unique=True)),
                ('slug', models.SlugField(max_length=60, unique=True)),
                ('renews_certificates', models.BooleanField(default=False)),
            ],
            options={
                'ordering': ['name'],
            },
        ),
        migrations.AlterField(
            model_name='platform',
            name='kind',
            field=models.CharField(max_length=60),
        ),
        migrations.RunPython(create_kinds, drop_kinds),
    ]
