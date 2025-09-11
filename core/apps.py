from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'core'

    def ready(self):
        # Реєструємо HEIF/HEIC підтримку глобально
        try:
            import pillow_heif
            pillow_heif.register_heif_opener()
        except Exception:
            # Не валимо ініціалізацію, якщо опенер не зареєструвався
            pass


