# Lookify - AI-Powered Virtual Try-On Platform

Lookify is a Django-based web application that enables users to virtually try on clothing items using artificial intelligence. The platform leverages Google's Gemini AI model to create realistic try-on experiences by seamlessly integrating clothing items onto user photos.

## 🚀 Features

- **AI-Powered Virtual Try-On**: Uses Google Gemini AI to create realistic clothing try-on effects
- **Multiple Item Support**: Upload and try on multiple clothing items simultaneously
- **Interactive Image Selection**: Preview uploaded images before processing
- **Custom Prompts**: Add specific instructions for AI processing
- **Mask Selection**: Optional mask functionality for precise item placement
- **Responsive Design**: Modern web interface with intuitive user experience
- **Image Processing**: Automatic image optimization and validation

## 🛠️ Technology Stack

- **Backend**: Django 5.2.5
- **AI Integration**: Google Generative AI (Gemini)
- **Image Processing**: Pillow (PIL)
- **Frontend**: HTML, CSS, JavaScript
- **Database**: SQLite (development)
- **Environment**: Python 3.13+

## 📋 Prerequisites

- Python 3.13 or higher
- Google Gemini API key
- Virtual environment (recommended)

## 🚀 Installation

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd lookify
   ```

2. **Create and activate virtual environment**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Set up environment variables**
   Create a `.env` file in the project root:
   ```env
   GOOGLE_API_KEY=your_gemini_api_key_here
   USE_GEMINI=True
   GEMINI_MODEL=gemini-1.5-flash
   REQUEST_TIMEOUT=300
   ```

5. **Run database migrations**
   ```bash
   python manage.py migrate
   ```

6. **Start the development server**
   ```bash
   python manage.py runserver
   ```

7. **Access the application**
   Open your browser and navigate to `http://127.0.0.1:8000`

## 📁 Project Structure

```
lookify/
├── fitting/                    # Main Django app
│   ├── services/              # AI and image processing services
│   │   ├── gemini_client.py   # Google Gemini AI integration
│   │   └── image_utils.py     # Image processing utilities
│   ├── forms.py               # Django forms
│   ├── views.py               # View logic
│   └── urls.py                # URL routing
├── lookify/                   # Django project settings
│   ├── settings.py            # Project configuration
│   └── urls.py                # Main URL configuration
├── templates/                 # HTML templates
│   ├── base.html              # Base template
│   ├── upload.html            # File upload interface
│   ├── preview.html           # Image preview
│   └── result.html            # Results display
├── media/                     # Uploaded and generated images
├── requirements.txt           # Python dependencies
└── manage.py                  # Django management script
```

## 🔧 Configuration

### Environment Variables

- `GOOGLE_API_KEY`: Your Google Gemini API key
- `USE_GEMINI`: Enable/disable AI processing (True/False)
- `GEMINI_MODEL`: Gemini model to use (default: gemini-1.5-flash)
- `REQUEST_TIMEOUT`: API request timeout in seconds (default: 300)

### Settings

Key settings can be modified in `lookify/settings.py`:
- `DEBUG`: Development mode (set to False in production)
- `ALLOWED_HOSTS`: Configure for production deployment
- `MEDIA_ROOT`: Directory for uploaded files
- `MEDIA_URL`: URL prefix for media files

## 🎯 Usage

1. **Upload Images**: Upload a photo of yourself and one or more clothing items
2. **Preview**: Review uploaded images before processing
3. **Customize**: Add optional prompts or selection masks
4. **Process**: Generate AI-powered try-on results
5. **Download**: Save and share your virtual try-on images

## 🔒 Security Considerations

- Keep your API keys secure and never commit them to version control
- Use environment variables for sensitive configuration
- Implement proper authentication for production use
- Validate and sanitize all user uploads
- Set appropriate file size limits

## 🚀 Deployment

For production deployment:

1. Set `DEBUG = False` in settings
2. Configure `ALLOWED_HOSTS` with your domain
3. Use a production database (PostgreSQL recommended)
4. Set up static file serving
5. Configure HTTPS
6. Use a production WSGI server (Gunicorn, uWSGI)

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 🙏 Acknowledgments

- Google Gemini AI for providing the AI capabilities
- Django community for the excellent web framework
- Pillow library for image processing capabilities

## 📞 Support

For support and questions, please open an issue in the repository or contact the development team.

---

**Note**: This application requires a valid Google Gemini API key to function properly. Make sure to obtain one from the Google AI Studio before using the application.
