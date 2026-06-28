# Gmail Productivity Dashboard

A productivity-focused Gmail dashboard with priority inbox, quick actions, smart email categorization, and **job search tracking** features.

![Python](https://img.shields.io/badge/Python-3.9+-blue.svg)
![Flask](https://img.shields.io/badge/Flask-2.0+-green.svg)
![License](https://img.shields.io/badge/License-MIT-yellow.svg)

## Features

- 🎯 **Priority Inbox** - Emails automatically sorted by priority score
- ⚡ **Quick Actions** - Star, archive, delete with one click
- 🏷️ **Smart Categories** - Auto-categorization (Urgent, Jobs, Meetings, Finance, etc.)
- 📊 **Stats Overview** - Inbox, unread, starred counts at a glance
- 🔍 **Search** - Full Gmail search capabilities
- 📁 **Folder Navigation** - Access all Gmail folders
- 💼 **Job Search Filters** - Quick filters for job-related emails
- 📅 **Interview Tracker** - Weekly chart of interview emails (last 2 months)
- 😴 **Snooze Emails** - Hide emails until later
- ⏰ **Reminders** - Set follow-up reminders
- 📈 **Daily Digest** - Summary of email activity

## Setup

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Set Up Google Cloud Credentials

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select existing
3. Enable the **Gmail API**:
   - Go to "APIs & Services" → "Library"
   - Search "Gmail API" → Enable
4. Configure **OAuth Consent Screen**:
   - Go to "APIs & Services" → "OAuth consent screen"
   - Select "External" user type
   - Fill in app name and your email
   - Add scopes: `gmail.readonly`, `gmail.modify`, `gmail.labels`
   - Add your email as a test user
5. Create **OAuth Credentials**:
   - Go to "APIs & Services" → "Credentials"
   - Click "Create Credentials" → "OAuth client ID"
   - Application type: **Web application**
   - Name: Gmail Dashboard
   - Authorized redirect URIs: `http://localhost:5000/oauth2callback`
6. Download the credentials JSON file
7. Rename it to `credentials.json` and place in this folder

### 3. Run the App

```bash
python app.py
```

Open http://localhost:5000 in your browser.

## Usage

1. Click "Sign in with Google" on the login page
2. Authorize the app to access your Gmail
3. Browse your priority inbox with smart categorization
4. Use quick actions to manage emails efficiently

## Priority Scoring

Emails are scored based on:
- Unread status (+20)
- Starred (+30)
- Important label (+25)
- Urgent keywords in subject (+35)
- Recency within 24 hours (+15)

## Categories

- 🔥 **Urgent** - Contains urgent/ASAP keywords
- 📅 **Meetings** - Calendar invites, meeting requests
- 💰 **Finance** - Invoices, payments, receipts
- 🤖 **Automated** - No-reply senders
- 🏷️ **Promotions** - Gmail's promotions category
- 👥 **Social** - Gmail's social category
- 🔔 **Updates** - Gmail's updates category
- 📧 **Primary** - Everything else

## Security

- OAuth 2.0 authentication
- No passwords stored
- Session-based credential storage
- Read-only access by default (modify only for actions you take)

## Project Structure

```
gmail-dashboard/
├── app.py                    # Flask backend (API routes, Gmail integration)
├── credentials.json          # Your Google OAuth credentials (DO NOT COMMIT)
├── credentials.example.json  # Template for credentials
├── requirements.txt          # Python dependencies
├── README.md                 # This file
├── .gitignore               # Git ignore rules
└── templates/
    └── dashboard.html       # Frontend (HTML + Tailwind CSS + JavaScript)
```

## Screenshots

*Coming soon*

## Contributing

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

- [Flask](https://flask.palletsprojects.com/)
- [Google Gmail API](https://developers.google.com/gmail/api)
- [Tailwind CSS](https://tailwindcss.com/)
