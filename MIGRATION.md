# Міграція з Django Templates на REST API

## Огляд змін

Проєкт було повністю переписано з Django templates/views на повноцінне REST API на Django REST Framework (DRF), зберігши всю бізнес-логіку, валідації та права доступу.

## Мапа міграції view → endpoint

| Старий endpoint | Новий API endpoint | HTTP методи | Опис |
|---|---|---|---|
| `/` | `/api/v1/` | GET | Головна сторінка API |
| `/clothes/upload/` | `/api/v1/clothes/upload/` | POST | Завантаження фото для приміряння одягу |
| `/clothes/preview/` | `/api/v1/clothes/preview/` | GET | Прев'ю завантажених фото |
| `/clothes/process/` | `/api/v1/clothes/process/` | POST | Обробка фото через AI |
| `/clothes/result/` | `/api/v1/clothes/result/` | GET | Результати обробки |
| `/hair/upload/` | `/api/v1/hair/upload/` | POST | Завантаження фото для приміряння зачісок |
| `/hair/preview/` | `/api/v1/hair/preview/` | GET | Прев'ю завантажених фото зачісок |
| `/hair/process/` | `/api/v1/hair/process/` | POST | Обробка фото зачісок через AI |
| `/hair/result/` | `/api/v1/hair/result/` | GET | Результати обробки зачісок |

## Нові ендпоінти аутентифікації

| Endpoint | HTTP методи | Опис |
|---|---|---|
| `/api/v1/auth/login/` | POST | Логін користувача з JWT токенами |
| `/api/v1/auth/refresh/` | POST | Оновлення JWT токенів |
| `/api/v1/auth/me/` | GET | Інформація про поточного користувача |
| `/api/v1/auth/logout/` | POST | Логаут користувача |

## OpenAPI документація

- **Swagger UI**: `/api/docs/`
- **ReDoc**: `/api/redoc/`
- **Schema**: `/api/schema/`

## Зміни в архітектурі

### 1. Serializers замість Forms
- `UploadForm` → `UploadSerializer`
- `ProcessForm` → `ProcessSerializer`
- Додано валідацію зображень з підтримкою HEIC
- Збережено всі валідації з оригінальних форм

### 2. API Views замість Template Views
- Function-based views з DRF декораторами
- Уніфіковані відповіді з статус-кодами
- Структуровані помилки з кодами

### 3. Аутентифікація
- Session Authentication (backward compatibility)
- JWT Authentication (новий)
- Підтримка refresh токенів

### 4. Файли та медіа
- DRF MultiPartParser для завантаження файлів
- Валідація MIME типів та розмірів
- Безпечне збереження файлів

## Backward Compatibility

Всі старі URL автоматично редіректуються на нові API ендпоінти з повідомленням про міграцію.

## Налаштування

### Нові залежності
- `djangorestframework`
- `djangorestframework-simplejwt`
- `drf-spectacular`
- `django-cors-headers`
- `django-filter`

### DRF налаштування
- Глобальна пагінація (20 елементів на сторінку)
- Throttling (100/год для анонімів, 1000/год для користувачів)
- Фільтрація та пошук
- OpenAPI схема

## Тестування

Для тестування API використовуйте:

1. **Swagger UI**: http://localhost:8000/api/docs/
2. **cURL приклади**:

```bash
# Завантаження фото
curl -X POST "http://localhost:8000/api/v1/clothes/upload/" \
  -F "user_photo=@user.jpg" \
  -F "item_photos=@item1.jpg" \
  -F "item_photos=@item2.jpg" \
  -F "prompt_text=Try on this outfit"

# Прев'ю
curl -X GET "http://localhost:8000/api/v1/clothes/preview/"

# Обробка
curl -X POST "http://localhost:8000/api/v1/clothes/process/" \
  -H "Content-Type: application/json" \
  -d '{"additional_prompt": "Make it look natural"}'

# Результат
curl -X GET "http://localhost:8000/api/v1/clothes/result/"
```

## Логування

Додано структуроване логування для:
- Завантаження файлів
- AI обробки
- Помилок валідації
- Аутентифікації

## Безпека

- CORS налаштування для фронтенду
- CSRF захист для сесій
- JWT токени з обмеженим терміном дії
- Валідація файлів та MIME типів
- Безпечні шляхи для збереження файлів

