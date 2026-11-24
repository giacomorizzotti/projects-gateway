from django.contrib.auth.models import User
from django.db import models


class Identity(models.Model):
    """The provider account a local user signs in as, by its `sub`: the provider's permanent id
    for it. Bound at that user's first login, when the username claim names the user; from then
    on only that account gets in as them, even if another one later takes the username (OpenID
    Connect doesn't promise usernames stay unique or unchanged). `add_user --rebind` forgets it.
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='identities')
    # OIDC_ISSUER without its trailing slash: another provider means a new binding.
    issuer = models.CharField(max_length=255)
    # OpenID Connect Core §2: at most 255 ASCII characters.
    subject = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = 'identities'
        constraints = [
            models.UniqueConstraint(fields=['issuer', 'subject'], name='identity_unique_subject'),
            models.UniqueConstraint(fields=['user', 'issuer'], name='identity_one_per_issuer'),
        ]

    def __str__(self):
        return f'{self.user.username} = {self.subject} at {self.issuer}'
