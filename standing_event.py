import base64
import cgi
import datetime
import Cookie
import json
import os
import psycopg2
import re
import requests
import sys
import traceback
import urllib

HOST='https://www.regularlyscheduled.com'
APP_TITLE='Regularly Scheduled'
ADVANCE_DAYS=4
MAIL_FROM='Regularly Scheduled <jeff@jefftk.com>'
MAILGUN_URL='https://api.mailgun.net/v3/mg.regularlyscheduled.com/messages'
MAILGUN_API_KEY=os.environ['MAILGUN_API_KEY']


def link(*components, **kwargs):
    query_string = ''
    if kwargs:
        query_string = '?' + '&'.join(
            '%s=%s' % (k, v)
            for (k, v) in sorted(kwargs.items()))

    return '%s/%s%s' % (HOST, '/'.join(components), query_string)

def html_escape(s):
    for f,r in [['&', '&amp;'],
                ['"', '&quot;'],
                ['<', '&lt;'],
                ['>', '&gt;']]:
        s = s.replace(f,r)
    return s

def page(title, updest, body):
    if updest:
        up = '<a href="%s" id=up>&larr;</a>' % updest
    return '''\
<html>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
* {
  font-family: sans-serif;
  -webkit-appearance: none;
  -moz-appearance: none;
  appearance: none;
}
input, select, button {
  font-size: 110%%;
  padding: 10px;
  margin: 0;
}
input[type=radio] {
  -webkit-appearance: radio;
  -moz-appearance: radio;
  appearance: radio;
  margin: 10px;
}
body {
  background-color: #EEE;
  margin: 0;
  padding: 0;
}
#content {
  background-color: #FFF;
  margin: 0 auto;
  height: 100%%;
}
#page {
  padding: 10px;
  font-size: 120%%;
}
h1 {
  background-color: #CCC;
  margin: 0;
  padding: 10px;
}
#up {
  background-color: #DFDFDF;
  padding: 10px;
  display: block;
  text-decoration: none;
  color: black;
}

@media(min-width: 550px) {
  #content {
    width: 550px;
  }
}
</style>
<title>%s :: %s</title>
<div id=content>
<h1>%s</h1>
%s
<div id=page>
%s
</div>
</div>''' % (
    APP_TITLE, title, title,
    up if updest else '',
    body)

def selection_partial():
    return '''\
<div id=selection{n}>
<select name=nth>
  <option value=first>First</option>
  <option value=second>Second</option>
  <option value=third>Third</option>
  <option value=fourth>Fourth</option>
  <option value=fifth>Fifth</option>
</select>
<select name=day>
  <option value=mondays>Mondays</option>
  <option value=tuesdays>Tuesdays</option>
  <option value=wednesdays>Wednesdays</option>
  <option value=thursdays>Thursdays</option>
  <option value=fridays>Fridays</option>
  <option value=saturdays>Saturdays</option>
  <option value=sundasy>Sundays</option>
</select>
<button type=button onclick='remove({n})'>remove</button>
</div>
'''

def index(db, u_email, u_data):
    red_star = '<font color=red>*</font>&nbsp;'
    title_note = selection_note = email_note = ''

    top_note = ''

    missing = False
    if u_data:
        if 'title' not in u_data or len(u_data['title']) != 1:
            missing = True
            title_note = red_star

        if ('email' not in u_data or len(u_data['email']) != 1 or
            '@' not in u_data['email'][0]):
            missing = True
            email_note = red_star

        if ('day' not in u_data or 'nth' not in u_data or
            len(u_data['day']) == 0 or len(u_data['day']) != len(u_data['nth'])):
            missing = True
            selection_note = red_star

        if missing:
            top_note = '<i>Please correct the starred fields below.</i><p>'

    if u_data and not missing:
        u_title, = u_data['title']
        title = re.sub("[^A-Za-z0-9 .,]", "-", u_title)
        title = re.sub("-+", "-", title)
        title = re.sub("^-*", "", title)
        title = re.sub("-*$", "", title)

        u_form_email, = u_data['email']
        if not u_data['day'] or len(u_data['day']) != len(u_data['nth']):
            raise Exception('invalid nth-day pairs')

        event_id = nonce()

        confirmed = u_email and (u_email == u_form_email)
        db.execute("INSERT INTO events (event_id, title, admin_email, confirmed) "
                   "VALUES (%s, %s, %s, %s)",
                   (event_id, title, u_form_email, bool(confirmed)))
        member_nonce = create_user(db, u_form_email)

        for u_day, u_nth in zip(u_data['day'], u_data['nth']):
            db.execute("INSERT INTO recurrences (event_id, day, nth) "
                       "VALUES (%s, %s, %s)",
                       (event_id, u_day, u_nth))

        db.execute('INSERT INTO members (event_id, email, confirmed) '
                   'VALUES (%s, %s, %s)',
                   (event_id, u_form_email, bool(confirmed)))

        if confirmed:
            return '<meta http-equiv="refresh" content="0; url=%s">' % link(
                'event', event_id)
        else:
            send_email(u_form_email, 'Confirm your regularly scheduled event, %s' % title,
                   '''\
To see your regularly scheduled event, click:

    %s

If you didn't try to create an event, someone else must have entered your email.
You can ignore this message.  Sorry about that!  ''' % link(
    'event', event_id, id=member_nonce))

            top_note = '''\
<i>Sent email to %s with instructions on how to confirm
this event.</i><p>''' % html_escape(u_form_email)

    active_events = ''
    if u_email:
        db.execute('SELECT e.event_id, e.title '
                   '  FROM events AS e'
                   '  JOIN members AS m'
                   '    ON e.event_id = m.event_id'
                   ' WHERE m.email = %s'
                   '   AND m.confirmed'
                   ' ORDER BY e.title',
                   (u_email, ))
        active_list = db.fetchall()
        if active_list:
            active_events = 'Your events:<ul>%s</ul>' % '\n'.join(
                '<li><a href="%s">%s</a></li>' % (
                    link('event', event_id), title)
                for event_id, title in active_list)

    return page('Schedule a Regular Event', updest=None, body='''
%s
<form method=post>
%s<input type=text name=title placeholder=Title></text>
<br><br>
%s<div id=selections>
%s
</div>
<br>
<button type=button onclick='add_another()'>add another</button>
<br><br>
%s<input type=text name=email placeholder=Email%s></input>
<br><br>
<input type=submit value=create></input>
</form>

<script>
current_max = 1;
function remove(n) {
  document.getElementById('selection' + n).remove();
}
function add_another() {
  current_max++;
  var selection_partial=%s;

  var selection_div = document.createElement('div');
  selection_div.innerHTML = selection_partial.replace(/\{n\}/g, current_max);

  document.getElementById('selections').appendChild(selection_div);
}
</script>
%s
''' % (top_note,
       title_note,
       selection_note,
       selection_partial().replace('{n}', '1'),
       email_note,
       ' value="%s"' % html_escape(u_email) if u_email else '',
       json.dumps(selection_partial()),
       active_events))

def nonce():
    # makes a web-safe 12-char nonce
    return base64.b64encode(os.urandom(9),altchars=b'-_')

def send_email(address, subject, body):
    send_emails([address], subject, body, {address: ''})

def send_emails(addresses, subject, body, recipient_variables):
    data = {"from": MAIL_FROM,
            "to": addresses,
            "subject": subject,
            "text": body,
            "recipient-variables": json.dumps(recipient_variables)}

    r = requests.post(
        MAILGUN_URL,
        auth=("api", MAILGUN_API_KEY),
        data=data)
    if r.status_code != 200:
        raise Exception('Invalid Response from Mailgun: %r %r (%s)' % (
            r.status_code,
            r.text,
            json.dumps(data)))

def unsubscribe(db, u_event_id, u_member_nonce):
    db.execute('SELECT email FROM users WHERE nonce = %s',
               (u_member_nonce, ))
    (u_email, ), = db.fetchall()
    member_nonce = u_member_nonce

    db.execute('SELECT confirmed FROM members '
               'WHERE email = %s AND event_id = %s',
               (u_email, u_event_id))
    response = db.fetchall()
    if response:
        (confirmed, ), = response
        event_id = u_event_id

        if confirmed:
            db.execute('UPDATE members SET confirmed = false '
                       'WHERE email = %s AND event_id = %s',
                       (u_email, u_event_id))
            event_link = link('event', event_id, id=member_nonce)

            return page('Unsubscription Confirmed', '/', '''
%s will no longer receive email reminders about
this regularly scheduled event.

<p>

To re-subscribe, <a href="%s">click here</a>.
''' % (html_escape(u_email), event_link))

    return page('Not Subscribed', '/', '''
%s was already not receiving email reminders about
this regularly scheduled event.
    ''' % html_escape(u_email))

def matches(day_nth_pairs, consider):
    nth = {
        1: 'first',
        2: 'second',
        3: 'third',
        4: 'fourth',
        5: 'fifth'}[int(consider.day / 7) + 1]

    day = {
        1: 'mondays',
        2: 'tuesdays',
        3: 'wednesdays',
        4: 'thursdays',
        5: 'fridays',
        6: 'saturdays',
        7: 'sundays'}[consider.isoweekday()]

    return (day, nth) in day_nth_pairs

def create_user(db, u_email):
    db.execute('INSERT INTO users (email, nonce)'
               ' VALUES (%s, %s)'
               ' ON CONFLICT DO NOTHING',
               (u_email, nonce()))
    db.execute('SELECT nonce FROM users WHERE email = %s',
               (u_email, ))
    (member_nonce, ), = db.fetchall()
    return member_nonce

def event(db, u_event_id, u_email, member_nonce, data):
    top_note = ''
    db.execute('SELECT title, admin_email, confirmed FROM events where event_id=%s',
               (u_event_id, ))
    (title, admin_email, confirmed),  = db.fetchall()
    event_id = u_event_id
    if not confirmed:
        db.execute('UPDATE events SET confirmed=true WHERE event_id=%s',
                   (event_id, ))
        db.execute('UPDATE members SET confirmed=true '
                   ' WHERE event_id=%s AND email=%s',
                   (event_id, admin_email))

    if u_email:
        db.execute('SELECT confirmed FROM members '
                   ' WHERE event_id = %s and email = %s',
                   (event_id, u_email))
        response = db.fetchall()
        if response:
            (confirmed, ), = response
            if not confirmed:
                db.execute('UPDATE members SET confirmed = true '
                           ' WHERE event_id = %s and email = %s',
                           (event_id, u_email))
                receive = 'will now receive'
            else:
                receive = 'receives'

            top_note = '''\
<i>%s %s email reminders for this event; <a href="%s">unsubscribe</a></i>.<p>
''' % (html_escape(u_email),
       receive,
       link('unsubscribe', event_id, member_nonce))


    if data:
        u_form_email, = data['email']

        confirmed = u_email and (u_email == u_form_email)

        member_nonce = create_user(db, u_form_email)

        db.execute('INSERT INTO members (event_id, email, confirmed) '
                   'VALUES (%s, %s, %s)',
                   (event_id, u_form_email, bool(confirmed)))

        if confirmed:
            top_note = '''\
<i>%s will now receive email reminders for this event</i><p>''' % (
                   html_escape(u_email))
        else:
            confirm_url = link('event', event_id, id=member_nonce)

            send_email(u_email, "Confirm you'd like to join %s" % title, '''\
To join the regularly scheduled event %s, click:

    %s

If you don't know what this is about, someone else must have entered
your email.  Sorry about that!
''' % (title, confirm_url))

            top_note = '''\
<i>Sent email to %s with a link to confirm.
''' % html_escape(u_email)

    db.execute('SELECT day, nth FROM recurrences WHERE event_id=%s',
               (event_id, ))
    recurrences_raw = list(db.fetchall())
    recurrences = '<ul>%s</ul>' % '\n'.join(
        '<li>%s %s</li>' % (html_escape(u_nth),
                            html_escape(u_day))
        for u_day, u_nth in recurrences_raw)

    now = datetime.datetime.now()
    upcoming_dates = []

    # Select up to five occurrences in next 90 days.
    for i in range(90):
        if len(upcoming_dates) >= 5:
            break

        consider = now + datetime.timedelta(days=i)
        if matches(recurrences_raw, consider):
            upcoming_dates.append(consider.strftime('%F'))

    upcoming = '<ul>%s</ul>' % '\n'.join(
        '<li><a href="%s">%s</a></li>' % (
            link('event', event_id, upcoming_date),
            upcoming_date)
            for upcoming_date in upcoming_dates)

    db.execute('SELECT email FROM members '
               'WHERE event_id=%s AND confirmed=true '
               'ORDER BY email ASC', (event_id, ))
    member_emails = list(u_email for u_email, in db.fetchall())
    if member_emails:
        members = '<ul>%s</ul>' % '\n'.join(
            '<li>%s</li>' % html_escape(u_email) for
            u_email in member_emails)
    else:
        members = 'currently no one<br><br>'

    calendar_link = link('ical', event_id)

    return page(title, '/', '''
%s
Happens on:
%s
Upcoming dates:
%s
Members:
%s
Calendar link: <a href="%s">ical</a><br><br>
<form method=post>
<input type=text name=email placeholder=Email%s></text>
<input type=submit value=join>
''' % (
    top_note,
    recurrences,
    upcoming,
    members,
    calendar_link,
    ' value="%s"' % html_escape(u_email) if u_email else ''))

def send_emails_for_today():
    with psycopg2.connect(
        "dbname='standing-events' user='%s' host='localhost'"
        " password='%s'" % (os.environ['DB_USER'],
                            os.environ['DB_PASS'])) as conn:
        with conn.cursor() as db:
            advance = datetime.datetime.now() + datetime.timedelta(
                days=ADVANCE_DAYS)
            advance_date = advance.strftime('%F')

            db.execute('SELECT event_id, day, nth from recurrences')
            to_send_event_ids = set(
                event_id
                for event_id, u_day, u_nth in db.fetchall()
                if matches([(u_day, u_nth)], advance))

            for event_id in to_send_event_ids:
                db.execute('SELECT title FROM events WHERE event_id=%s',
                           (event_id, ))
                (title, ), = db.fetchall()

                db.execute('SELECT u.email, u.nonce '
                           ' FROM members AS m'
                           ' JOIN users AS u'
                           '   ON m.email = u.email'
                           ' WHERE m.confirmed = true'
                           '   AND m.event_id = %s'
                           '   AND u.email NOT IN ('
                           '   SELECT email FROM rsvps'
                           '    WHERE event_id = %s'
                           '      AND date = %s)',
                           (event_id, event_id, advance_date))

                recipient_variables = dict(
                    (u_email, {'member_nonce': member_nonce})
                    for u_email, member_nonce in db.fetchall())
                if recipient_variables:
                    day = advance.strftime('%A')
                    send_emails(list(recipient_variables.keys()),
                                'Reminder: %s is this %s; rsvp?' % (
                                    title, day),
                                '''\
%s is this %s.  RSVP:

    %s''' % (title, day, link(
        'event', event_id, advance_date,
        id='%recipient.member_nonce%')),
                                recipient_variables)


def event_date(db, u_event_id, u_date, u_email, member_nonce, u_data):
    date = html_escape(u_date)
    top_note = ''

    db.execute('SELECT title FROM events WHERE event_id = %s',
               (u_event_id, ))
    (title,), = db.fetchall()
    event_id = u_event_id

    if u_email:
        db.execute('SELECT email FROM members'
                   ' WHERE event_id = %s AND email = %s',
                   (event_id, u_email))
        # verifying that they're a member
        (_, ), = db.fetchall()

        if u_data:
            u_attending, = u_data['attending']

            if 'comment' in u_data:
                u_comment, = u_data['comment']
            else:
                u_comment = None

            db.execute('DELETE FROM rsvps WHERE event_id = %s and email = %s', (
                event_id, u_email))
            db.execute('INSERT INTO rsvps '
                       '(event_id, email, date, attending, comment) '
                       'VALUES (%s, %s, %s, %s, %s)', (
                           event_id, u_email, u_date, u_attending == 'yes',
                           u_comment))
            top_note = '<i>RSVPd %s</i><p>' % (
                'Yes' if u_attending == 'yes' else 'No')

    db.execute('SELECT attending, comment FROM rsvps '
               ' WHERE event_id = %s'
               '   AND email = %s'
               '   AND date = %s',
               (event_id, u_email, u_date))
    results = db.fetchall()
    if results:
        (attending, comment), = results
    else:
        attending = comment = None

    rsvp_form = '''\
<form method=post>
<input type=radio name=attending value=yes%s>Yes</input><br>
<input type=radio name=attending value=no%s>No</input><br>
<br>
<input type=text name=comment placeholder=Comments>%s</input><br>
<br>
<input type=submit value=RSVP></submit>
''' % (' checked' if attending is True else '',
       ' checked' if attending is False else '',
       comment or '')

    db.execute('SELECT title FROM events WHERE event_id=%s',
               (event_id, ))
    (title, ), = db.fetchall()

    db.execute('SELECT email, attending, comment FROM rsvps '
               'WHERE event_id=%s AND date=%s '
               'ORDER by email ASC', (event_id, u_date))
    rsvps = ['<li><p>%s: %s%s' % (
        html_escape(u_email),
        'Yes' if attending else 'No',
        ('<blockquote><i>%s</i></blockquote>' % html_escape(u_comment)
         if u_comment else ''))
             for u_email, attending, u_comment in db.fetchall()]
    date = html_escape(u_date)

    if rsvps:
        current_rsvps = '<ul>%s</ul>' % '\n'.join(rsvps)
    else:
        current_rsvps = 'No RSVPs yet.'

    return page('%s: %s' % (title, date), link('event', event_id), '%s%s<p>%s' % (
        top_note, rsvp_form, current_rsvps))

def ical(db, u_event_id):
    db.execute('SELECT title FROM events where event_id=%s',
               (u_event_id, ))
    (title, ),  = db.fetchall()
    event_id = u_event_id

    db.execute('SELECT day, nth FROM recurrences WHERE event_id=%s',
               (event_id, ))
    u_recurrences_raw = list(db.fetchall())

    now = datetime.datetime.now()
    upcoming_dates = []

    # Select up all occurrences in next 90 days.
    for i in range(90):
        consider = now + datetime.timedelta(days=i)
        if matches(u_recurrences_raw, consider):
            upcoming_dates.append(consider.strftime('%Y%m%d'))

    return '''\
BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Google Inc//Google Calendar 70.9054//EN
%s
END:VCALENDAR''' % '\n'.join(
    '''\
BEGIN:VEVENT
DTSTART;VALUE=DATE:%s
DTEND;VALUE=DATE:%s
SUMMARY: %s
END:VEVENT''' % (
    upcoming_date,
    upcoming_date,
    title) for upcoming_date in upcoming_dates)

def route(u_path, environ):
    with psycopg2.connect(
        "dbname='standing-events' user='%s' host='localhost'"
        " password='%s'" % (os.environ['DB_USER'],
                            os.environ['DB_PASS'])) as conn:
        with conn.cursor() as db:
            if 'QUERY_STRING' in environ:
                query = cgi.parse_qs(environ['QUERY_STRING'])
                if 'id' in query and len(query['id']) == 1:
                    u_member_nonce, = query['id']
                    db.execute('SELECT nonce FROM users WHERE nonce = %s',
                               (u_member_nonce, ))
                    if db.fetchall():
                        if u_path.startswith('/'):
                            u_path = u_path[1:]
                        return '''\
<meta http-equiv="set-cookie" content="id=%s; Path=/">
<meta http-equiv="refresh" content="0; url=%s">
''' % (u_member_nonce, link(html_escape(u_path)))

            u_email = None
            member_nonce = None
            if 'HTTP_COOKIE' in environ:
                cookies = Cookie.SimpleCookie(environ['HTTP_COOKIE'])
                if 'id' in cookies:
                    u_member_nonce = cookies['id'].value
                    db.execute('SELECT email FROM users WHERE nonce = %s',
                               (u_member_nonce, ))
                    results = db.fetchall()
                    if results:
                        (u_email, ), = results
                        member_nonce = u_member_nonce
                    else:
                        u_email = None

            if (environ['CONTENT_LENGTH'] and
                int(environ['CONTENT_LENGTH']) > 0):

                u_data = cgi.parse_qs(
                    environ['wsgi.input'].read(
                        int(environ['CONTENT_LENGTH'])))
            else:
                u_data = {}

            if u_path in ['', '/']:
                return index(db, u_email, u_data)

            if u_path.startswith('/event/'):
                u_rest = u_path[len('/event/'):]
                u_pieces = u_rest.split('/')
                if len(u_pieces) == 1:
                    u_event_id, = u_pieces
                    return event(db, u_event_id, u_email, member_nonce, u_data)
                elif len(u_pieces) == 2:
                    u_event_id, u_date = u_pieces
                    return event_date(
                        db, u_event_id, u_date, u_email, member_nonce, u_data)
                else:
                    return '%r not understood' % html_escape(u_path)

            if u_path.startswith('/ical/'):
                u_event_id = u_path.split('/')[-1]
                return ical(db, u_event_id)

            if u_path.startswith('/unsubscribe/'):
                u_rest = u_path[len('/unsubscribe/'):]
                u_event_id, u_member_nonce = u_rest.split('/')
                return unsubscribe(db, u_event_id, u_member_nonce)

            return '%r not understood' % html_escape(u_path)

def die500(start_response, e):
    trb = '%s: %s\n\n%s' % (e.__class__.__name__, e, traceback.format_exc())
    start_response('500 Internal Server Error',
                   [('content-type', 'text/plain')])
    return trb

def application(environ, start_response):
    u_path = environ['PATH_INFO']
    try:
        output = route(u_path, environ)
        start_response('200 OK', [('content-type', 'text/html'),
                                  ('cache-control', 'no-cache')])
    except Exception as e:
        output = die500(start_response, e)

    return (output.encode('utf8'), )
if __name__ == '__main__':
    if False:
        def start_response(status_code, headers):
            print(status_code)
            for k, v in headers:
                print('%s: %s' % (k, v))
            print('')
        environ = {'PATH_INFO': sys.argv[1]}
        for x in application(environ, start_response):
            for l in x.split(b'\n'):
                print(l)
    if True:
        send_emails_for_today()
