import os
import json
import base64
import threading
import time
from datetime import datetime, timedelta
from flask import Flask, redirect, url_for, session, render_template, request, jsonify
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from email.utils import parsedate_to_datetime
import re

app = Flask(__name__)
app.secret_key = os.urandom(24)

# In-memory storage for snoozed emails and reminders (use database in production)
snoozed_emails = {}  # {email_id: {'until': datetime, 'email_data': {...}}}
reminders = {}  # {email_id: {'time': datetime, 'note': str}}

# Allow OAuth over HTTP for local development
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

SCOPES = [
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/gmail.modify',
    'https://www.googleapis.com/auth/gmail.labels'
]

CLIENT_SECRETS_FILE = 'credentials.json'


def get_credentials():
    """Get credentials from session."""
    if 'credentials' not in session:
        return None
    return Credentials(**session['credentials'])


def save_credentials(credentials):
    """Save credentials to session."""
    session['credentials'] = {
        'token': credentials.token,
        'refresh_token': credentials.refresh_token,
        'token_uri': credentials.token_uri,
        'client_id': credentials.client_id,
        'client_secret': credentials.client_secret,
        'scopes': credentials.scopes
    }


def get_gmail_service():
    """Get Gmail API service."""
    credentials = get_credentials()
    if not credentials:
        return None
    return build('gmail', 'v1', credentials=credentials)


def extract_email_body(payload):
    """Extract email body from payload."""
    body = ""
    if 'body' in payload and payload['body'].get('data'):
        body = base64.urlsafe_b64decode(payload['body']['data']).decode('utf-8', errors='ignore')
    elif 'parts' in payload:
        for part in payload['parts']:
            if part['mimeType'] == 'text/plain' and part['body'].get('data'):
                body = base64.urlsafe_b64decode(part['body']['data']).decode('utf-8', errors='ignore')
                break
            elif part['mimeType'] == 'text/html' and part['body'].get('data'):
                body = base64.urlsafe_b64decode(part['body']['data']).decode('utf-8', errors='ignore')
    return body[:500] + '...' if len(body) > 500 else body


def parse_email_header(headers, name):
    """Extract header value by name."""
    for header in headers:
        if header['name'].lower() == name.lower():
            return header['value']
    return ''


def categorize_email(subject, sender, labels):
    """Categorize email based on content and labels."""
    subject_lower = subject.lower()
    sender_lower = sender.lower()
    
    # Check Gmail categories first
    label_names = [l.lower() for l in labels]
    if 'category_promotions' in label_names:
        return {'name': 'Promotions', 'color': '#f59e0b', 'icon': '🏷️'}
    if 'category_social' in label_names:
        return {'name': 'Social', 'color': '#3b82f6', 'icon': '👥'}
    if 'category_updates' in label_names:
        return {'name': 'Updates', 'color': '#8b5cf6', 'icon': '🔔'}
    if 'category_forums' in label_names:
        return {'name': 'Forums', 'color': '#06b6d4', 'icon': '💬'}
    
    # Keyword-based categorization
    if any(word in subject_lower for word in ['urgent', 'asap', 'important', 'action required']):
        return {'name': 'Urgent', 'color': '#ef4444', 'icon': '🔥'}
    if any(word in subject_lower for word in ['job', 'career', 'hiring', 'position', 'opportunity', 'application', 'recruiter', 'recruitment', 'interview', 'offer letter', 'resume', 'candidate', 'employment', 'job opening', 'we are hiring', 'your application', 'thank you for applying', 'next steps', 'assessment', 'coding challenge', 'technical interview', 'onboarding', 'background check', 'start date']):
        return {'name': 'Jobs', 'color': '#059669', 'icon': '💼'}
    if any(word in subject_lower for word in ['meeting', 'calendar', 'invite', 'schedule']):
        return {'name': 'Meetings', 'color': '#10b981', 'icon': '📅'}
    if any(word in subject_lower for word in ['invoice', 'payment', 'receipt', 'order']):
        return {'name': 'Finance', 'color': '#6366f1', 'icon': '💰'}
    if 'noreply' in sender_lower or 'no-reply' in sender_lower:
        return {'name': 'Automated', 'color': '#6b7280', 'icon': '🤖'}
    
    return {'name': 'Primary', 'color': '#1f2937', 'icon': '📧'}


def get_priority_score(email_data):
    """Calculate priority score for email."""
    score = 50  # Base score
    
    # Unread emails get higher priority
    if email_data.get('unread'):
        score += 20
    
    # Starred emails
    if email_data.get('starred'):
        score += 30
    
    # Important label
    if 'IMPORTANT' in email_data.get('labels', []):
        score += 25
    
    # Urgent keywords
    subject = email_data.get('subject', '').lower()
    if any(word in subject for word in ['urgent', 'asap', 'important']):
        score += 35
    
    # Recent emails (within 24 hours)
    if email_data.get('date'):
        try:
            email_date = datetime.fromisoformat(email_data['date'].replace('Z', '+00:00'))
            if datetime.now(email_date.tzinfo) - email_date < timedelta(hours=24):
                score += 15
        except:
            pass
    
    return min(score, 100)


@app.route('/')
def index():
    """Main dashboard page."""
    credentials = get_credentials()
    if not credentials:
        return render_template('login.html')
    return render_template('dashboard.html')


@app.route('/authorize')
def authorize():
    """Start OAuth flow."""
    if not os.path.exists(CLIENT_SECRETS_FILE):
        return render_template('setup.html')
    
    flow = Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE,
        scopes=SCOPES,
        redirect_uri='http://localhost:5000/oauth2callback'
    )
    authorization_url, state = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true',
        prompt='consent'
    )
    session['state'] = state
    return redirect(authorization_url)


@app.route('/oauth2callback')
def oauth2callback():
    """Handle OAuth callback."""
    state = session.get('state')
    flow = Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE,
        scopes=SCOPES,
        state=state,
        redirect_uri='http://localhost:5000/oauth2callback'
    )
    flow.fetch_token(authorization_response=request.url)
    save_credentials(flow.credentials)
    return redirect(url_for('index'))


@app.route('/logout')
def logout():
    """Clear session and logout."""
    session.clear()
    return redirect(url_for('index'))


@app.route('/api/profile')
def api_profile():
    """Get user profile."""
    service = get_gmail_service()
    if not service:
        return jsonify({'error': 'Not authenticated'}), 401
    
    try:
        profile = service.users().getProfile(userId='me').execute()
        return jsonify(profile)
    except HttpError as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/stats')
def api_stats():
    """Get inbox statistics."""
    service = get_gmail_service()
    if not service:
        return jsonify({'error': 'Not authenticated'}), 401
    
    try:
        # Get label stats
        labels_response = service.users().labels().list(userId='me').execute()
        labels = labels_response.get('labels', [])
        
        stats = {
            'inbox': 0,
            'unread': 0,
            'starred': 0,
            'drafts': 0,
            'sent': 0,
            'spam': 0,
            'trash': 0
        }
        
        for label in labels:
            label_info = service.users().labels().get(userId='me', id=label['id']).execute()
            label_name = label['name'].lower()
            
            if label_name == 'inbox':
                stats['inbox'] = label_info.get('messagesTotal', 0)
                stats['unread'] = label_info.get('messagesUnread', 0)
            elif label_name == 'starred':
                stats['starred'] = label_info.get('messagesTotal', 0)
            elif label_name == 'draft':
                stats['drafts'] = label_info.get('messagesTotal', 0)
            elif label_name == 'sent':
                stats['sent'] = label_info.get('messagesTotal', 0)
            elif label_name == 'spam':
                stats['spam'] = label_info.get('messagesTotal', 0)
            elif label_name == 'trash':
                stats['trash'] = label_info.get('messagesTotal', 0)
        
        return jsonify(stats)
    except HttpError as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/emails')
def api_emails():
    """Get emails with categorization."""
    service = get_gmail_service()
    if not service:
        return jsonify({'error': 'Not authenticated'}), 401
    
    try:
        query = request.args.get('q', '')
        label = request.args.get('label', 'INBOX')
        max_results = int(request.args.get('max', 20))
        
        # Build query
        q = query if query else None
        
        results = service.users().messages().list(
            userId='me',
            labelIds=[label] if label else None,
            q=q,
            maxResults=max_results
        ).execute()
        
        messages = results.get('messages', [])
        emails = []
        
        for msg in messages:
            msg_data = service.users().messages().get(
                userId='me',
                id=msg['id'],
                format='full'
            ).execute()
            
            headers = msg_data.get('payload', {}).get('headers', [])
            labels = msg_data.get('labelIds', [])
            
            subject = parse_email_header(headers, 'Subject') or '(No Subject)'
            sender = parse_email_header(headers, 'From')
            date = parse_email_header(headers, 'Date')
            
            # Parse sender name and email
            sender_match = re.match(r'(.+?)\s*<(.+?)>', sender)
            if sender_match:
                sender_name = sender_match.group(1).strip('"')
                sender_email = sender_match.group(2)
            else:
                sender_name = sender
                sender_email = sender
            
            # Parse date
            try:
                parsed_date = parsedate_to_datetime(date)
                date_iso = parsed_date.isoformat()
                date_display = parsed_date.strftime('%b %d, %I:%M %p')
            except:
                date_iso = ''
                date_display = date
            
            email_data = {
                'id': msg['id'],
                'threadId': msg_data.get('threadId'),
                'subject': subject,
                'sender_name': sender_name,
                'sender_email': sender_email,
                'date': date_iso,
                'date_display': date_display,
                'snippet': msg_data.get('snippet', ''),
                'labels': labels,
                'unread': 'UNREAD' in labels,
                'starred': 'STARRED' in labels,
                'important': 'IMPORTANT' in labels,
                'category': categorize_email(subject, sender, labels)
            }
            
            email_data['priority'] = get_priority_score(email_data)
            emails.append(email_data)
        
        # Sort by priority
        emails.sort(key=lambda x: x['priority'], reverse=True)
        
        return jsonify({'emails': emails})
    except HttpError as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/interview-stats')
def api_interview_stats():
    """Get interview-related email stats grouped by week."""
    service = get_gmail_service()
    if not service:
        return jsonify({'error': 'Not authenticated'}), 401
    
    try:
        # Search for interview-related emails from the last 2 months (60 days)
        interview_query = 'subject:(interview OR assessment OR "coding challenge" OR "technical round" OR "phone screen" OR "video call" OR "scheduled" OR "calendar invite" OR recruiter OR hiring OR "next round") newer_than:60d'
        
        results = service.users().messages().list(
            userId='me',
            q=interview_query,
            maxResults=100
        ).execute()
        
        messages = results.get('messages', [])
        
        # Group by week
        from collections import defaultdict
        weekly_counts = defaultdict(int)
        interview_details = []
        
        for msg in messages:
            msg_data = service.users().messages().get(
                userId='me',
                id=msg['id'],
                format='metadata',
                metadataHeaders=['Subject', 'From', 'Date']
            ).execute()
            
            headers = msg_data.get('payload', {}).get('headers', [])
            subject = parse_email_header(headers, 'Subject') or '(No Subject)'
            sender = parse_email_header(headers, 'From') or ''
            date_str = parse_email_header(headers, 'Date')
            
            try:
                parsed_date = parsedate_to_datetime(date_str)
                # Get ISO week number and year
                year, week_num, _ = parsed_date.isocalendar()
                week_key = f"{year}-W{week_num:02d}"
                week_start = parsed_date - timedelta(days=parsed_date.weekday())
                week_label = week_start.strftime('%b %d')
                
                weekly_counts[week_key] = {
                    'count': weekly_counts.get(week_key, {}).get('count', 0) + 1,
                    'label': week_label,
                    'year': year,
                    'week': week_num
                }
                
                interview_details.append({
                    'id': msg['id'],
                    'subject': subject,
                    'sender': sender,
                    'date': parsed_date.strftime('%Y-%m-%d'),
                    'week_key': week_key
                })
            except:
                pass
        
        # Generate all 8 weeks (last 2 months) with proper labels
        today = datetime.now()
        weeks_data = []
        
        for i in range(7, -1, -1):  # 8 weeks ago to current week
            week_date = today - timedelta(weeks=i)
            year, week_num, _ = week_date.isocalendar()
            week_key = f"{year}-W{week_num:02d}"
            week_start = week_date - timedelta(days=week_date.weekday())
            week_label = week_start.strftime('%b %d')
            
            # Get count from our data or 0
            count = weekly_counts.get(week_key, {}).get('count', 0) if week_key in weekly_counts else 0
            
            weeks_data.append({
                'week': week_key,
                'label': week_label,
                'count': count
            })
        
        total_interviews = sum(d['count'] for d in weeks_data)
        this_week = weeks_data[-1]['count'] if weeks_data else 0
        last_week = weeks_data[-2]['count'] if len(weeks_data) >= 2 else 0
        
        return jsonify({
            'weeks': weeks_data,
            'total': total_interviews,
            'this_week': this_week,
            'last_week': last_week,
            'details': interview_details[:20]  # Last 20 interview emails
        })
    except HttpError as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/email/<email_id>')
def api_email_detail(email_id):
    """Get single email details."""
    service = get_gmail_service()
    if not service:
        return jsonify({'error': 'Not authenticated'}), 401
    
    try:
        msg_data = service.users().messages().get(
            userId='me',
            id=email_id,
            format='full'
        ).execute()
        
        headers = msg_data.get('payload', {}).get('headers', [])
        body = extract_email_body(msg_data.get('payload', {}))
        
        return jsonify({
            'id': email_id,
            'subject': parse_email_header(headers, 'Subject'),
            'from': parse_email_header(headers, 'From'),
            'to': parse_email_header(headers, 'To'),
            'date': parse_email_header(headers, 'Date'),
            'body': body,
            'labels': msg_data.get('labelIds', [])
        })
    except HttpError as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/email/<email_id>/star', methods=['POST'])
def api_star_email(email_id):
    """Toggle star on email."""
    service = get_gmail_service()
    if not service:
        return jsonify({'error': 'Not authenticated'}), 401
    
    try:
        action = request.json.get('action', 'add')
        if action == 'add':
            service.users().messages().modify(
                userId='me',
                id=email_id,
                body={'addLabelIds': ['STARRED']}
            ).execute()
        else:
            service.users().messages().modify(
                userId='me',
                id=email_id,
                body={'removeLabelIds': ['STARRED']}
            ).execute()
        return jsonify({'success': True})
    except HttpError as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/email/<email_id>/read', methods=['POST'])
def api_mark_read(email_id):
    """Mark email as read/unread."""
    service = get_gmail_service()
    if not service:
        return jsonify({'error': 'Not authenticated'}), 401
    
    try:
        action = request.json.get('action', 'read')
        if action == 'read':
            service.users().messages().modify(
                userId='me',
                id=email_id,
                body={'removeLabelIds': ['UNREAD']}
            ).execute()
        else:
            service.users().messages().modify(
                userId='me',
                id=email_id,
                body={'addLabelIds': ['UNREAD']}
            ).execute()
        return jsonify({'success': True})
    except HttpError as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/email/<email_id>/archive', methods=['POST'])
def api_archive_email(email_id):
    """Archive email."""
    service = get_gmail_service()
    if not service:
        return jsonify({'error': 'Not authenticated'}), 401
    
    try:
        service.users().messages().modify(
            userId='me',
            id=email_id,
            body={'removeLabelIds': ['INBOX']}
        ).execute()
        return jsonify({'success': True})
    except HttpError as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/email/<email_id>/trash', methods=['POST'])
def api_trash_email(email_id):
    """Move email to trash."""
    service = get_gmail_service()
    if not service:
        return jsonify({'error': 'Not authenticated'}), 401
    
    try:
        service.users().messages().trash(userId='me', id=email_id).execute()
        return jsonify({'success': True})
    except HttpError as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/labels')
def api_labels():
    """Get all labels."""
    service = get_gmail_service()
    if not service:
        return jsonify({'error': 'Not authenticated'}), 401
    
    try:
        results = service.users().labels().list(userId='me').execute()
        labels = results.get('labels', [])
        return jsonify({'labels': labels})
    except HttpError as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/email/<email_id>/snooze', methods=['POST'])
def api_snooze_email(email_id):
    """Snooze an email until a specified time."""
    service = get_gmail_service()
    if not service:
        return jsonify({'error': 'Not authenticated'}), 401
    
    try:
        data = request.json
        snooze_until = data.get('until')  # ISO format datetime
        
        # Parse the snooze time
        snooze_time = datetime.fromisoformat(snooze_until.replace('Z', '+00:00'))
        
        # Store snooze info
        snoozed_emails[email_id] = {
            'until': snooze_time.isoformat(),
            'snoozed_at': datetime.now().isoformat()
        }
        
        # Archive the email (remove from inbox)
        service.users().messages().modify(
            userId='me',
            id=email_id,
            body={'removeLabelIds': ['INBOX']}
        ).execute()
        
        return jsonify({'success': True, 'snoozed_until': snooze_time.isoformat()})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/snoozed')
def api_get_snoozed():
    """Get all snoozed emails."""
    now = datetime.now()
    active_snoozed = []
    expired = []
    
    for email_id, data in list(snoozed_emails.items()):
        snooze_time = datetime.fromisoformat(data['until'].replace('Z', '+00:00'))
        if snooze_time.replace(tzinfo=None) <= now:
            expired.append(email_id)
        else:
            active_snoozed.append({
                'id': email_id,
                'until': data['until'],
                'snoozed_at': data.get('snoozed_at')
            })
    
    return jsonify({
        'snoozed': active_snoozed,
        'expired_count': len(expired)
    })


@app.route('/api/email/<email_id>/unsnooze', methods=['POST'])
def api_unsnooze_email(email_id):
    """Unsnooze an email and move back to inbox."""
    service = get_gmail_service()
    if not service:
        return jsonify({'error': 'Not authenticated'}), 401
    
    try:
        # Remove from snoozed
        if email_id in snoozed_emails:
            del snoozed_emails[email_id]
        
        # Move back to inbox
        service.users().messages().modify(
            userId='me',
            id=email_id,
            body={'addLabelIds': ['INBOX']}
        ).execute()
        
        return jsonify({'success': True})
    except HttpError as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/email/<email_id>/reminder', methods=['POST'])
def api_set_reminder(email_id):
    """Set a reminder for an email."""
    try:
        data = request.json
        reminder_time = data.get('time')  # ISO format
        note = data.get('note', '')
        
        reminders[email_id] = {
            'time': reminder_time,
            'note': note,
            'created_at': datetime.now().isoformat()
        }
        
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/reminders')
def api_get_reminders():
    """Get all reminders."""
    now = datetime.now()
    active = []
    due = []
    
    for email_id, data in list(reminders.items()):
        reminder_time = datetime.fromisoformat(data['time'].replace('Z', '+00:00'))
        reminder_data = {
            'email_id': email_id,
            'time': data['time'],
            'note': data.get('note', ''),
            'created_at': data.get('created_at')
        }
        if reminder_time.replace(tzinfo=None) <= now:
            due.append(reminder_data)
        else:
            active.append(reminder_data)
    
    return jsonify({
        'active': active,
        'due': due
    })


@app.route('/api/reminder/<email_id>', methods=['DELETE'])
def api_delete_reminder(email_id):
    """Delete a reminder."""
    if email_id in reminders:
        del reminders[email_id]
    return jsonify({'success': True})


@app.route('/api/digest')
def api_daily_digest():
    """Get daily digest - summary of today's emails."""
    service = get_gmail_service()
    if not service:
        return jsonify({'error': 'Not authenticated'}), 401
    
    try:
        # Get today's date range
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        tomorrow = today + timedelta(days=1)
        
        # Gmail query for today's emails
        query = f'after:{today.strftime("%Y/%m/%d")} before:{tomorrow.strftime("%Y/%m/%d")}'
        
        results = service.users().messages().list(
            userId='me',
            q=query,
            maxResults=100
        ).execute()
        
        messages = results.get('messages', [])
        
        # Categorize today's emails
        digest = {
            'total': len(messages),
            'unread': 0,
            'by_category': {},
            'top_senders': {},
            'action_required': [],
            'date': today.strftime('%B %d, %Y')
        }
        
        for msg in messages[:50]:  # Limit processing
            msg_data = service.users().messages().get(
                userId='me',
                id=msg['id'],
                format='metadata',
                metadataHeaders=['From', 'Subject']
            ).execute()
            
            labels = msg_data.get('labelIds', [])
            headers = msg_data.get('payload', {}).get('headers', [])
            
            subject = ''
            sender = ''
            for h in headers:
                if h['name'] == 'Subject':
                    subject = h['value']
                elif h['name'] == 'From':
                    sender = h['value']
            
            # Count unread
            if 'UNREAD' in labels:
                digest['unread'] += 1
            
            # Categorize
            category = categorize_email(subject, sender, labels)
            cat_name = category['name']
            if cat_name not in digest['by_category']:
                digest['by_category'][cat_name] = {'count': 0, 'icon': category['icon'], 'color': category['color']}
            digest['by_category'][cat_name]['count'] += 1
            
            # Track senders
            sender_name = sender.split('<')[0].strip().strip('"')
            if sender_name not in digest['top_senders']:
                digest['top_senders'][sender_name] = 0
            digest['top_senders'][sender_name] += 1
            
            # Check for action required
            if any(word in subject.lower() for word in ['urgent', 'action required', 'asap', 'deadline']):
                digest['action_required'].append({
                    'id': msg['id'],
                    'subject': subject,
                    'sender': sender_name
                })
        
        # Sort top senders
        digest['top_senders'] = dict(sorted(
            digest['top_senders'].items(),
            key=lambda x: x[1],
            reverse=True
        )[:5])
        
        return jsonify(digest)
    except HttpError as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/focus/stats')
def api_focus_stats():
    """Get focus mode statistics."""
    service = get_gmail_service()
    if not service:
        return jsonify({'error': 'Not authenticated'}), 401
    
    try:
        # Get emails from last 7 days
        week_ago = datetime.now() - timedelta(days=7)
        query = f'after:{week_ago.strftime("%Y/%m/%d")}'
        
        results = service.users().messages().list(
            userId='me',
            q=query,
            maxResults=200
        ).execute()
        
        total_emails = results.get('resultSizeEstimate', 0)
        
        # Get unread count
        unread_results = service.users().messages().list(
            userId='me',
            q=f'{query} is:unread',
            maxResults=1
        ).execute()
        unread_count = unread_results.get('resultSizeEstimate', 0)
        
        # Calculate stats
        stats = {
            'emails_this_week': total_emails,
            'unread_count': unread_count,
            'avg_per_day': round(total_emails / 7, 1),
            'snoozed_count': len(snoozed_emails),
            'reminders_count': len(reminders),
            'inbox_zero_progress': max(0, 100 - (unread_count * 2))  # Simple metric
        }
        
        return jsonify(stats)
    except HttpError as e:
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    app.run(debug=True, port=5000)
