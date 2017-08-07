import base64
import cgi
import datetime
import json
import os
import psycopg2
import re
import requests
import sys
import traceback
import urllib

HOST='https://www.jefftk.com'
DEPLOY_LOCATION='/standing-event'
APP_TITLE='Standing Event'
ADVANCE_DAYS=4

def link(*components):
    return '%s%s/%s' % (HOST, DEPLOY_LOCATION,'/'.join(components))

def html_escape(s):
    for f,r in [['&', '&amp;'],
                ['<', '&lt;'],
                ['>', '&gt;']]:
        s = s.replace(f,r)
    return s

def page(title):
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
h1 {
  margin: 5px;
}
input, select, button {
  padding: 10px;
  margin: 5px;
  font-size: 120%%;
}
</style>
<title>%s%s</title>''' % (
    APP_TITLE, (': ' + title) if title else '')

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

def index():
    return page(title=None) + '''
<h1>Create a Standing Event</h1>
<form action=create method=post>
<input type=text name=title placeholder=Title></text>
<br><br>
<div id=selections>
%s
</div>
<br>
<button type=button onclick='add_another()'>add another</button>
<br><br>
<input type=text name=email placeholder=Email></input>
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
''' % (selection_partial().replace('{n}', '1'),
       json.dumps(selection_partial()))

def nonce():
    # makes a web-safe 12-char nonce
    return base64.b64encode(os.urandom(9),altchars=b'-_')

def interpret_post(environ):
    return cgi.parse_qs(environ['wsgi.input'].read(
        int(environ['CONTENT_LENGTH'])))

def send_email(address, subject, body):
    send_emails([address], subject, body, {address: ''})

def send_emails(addresses, subject, body, recipient_variables):
    data = {"from": "Standing Event <jeff@jefftk.com>",
            "to": addresses,
            "subject": subject,
            "text": body,
            "recipient-variables": json.dumps(recipient_variables)}
    r = requests.post(
        "https://api.mailgun.net/v3/mg.jefftk.com",
        auth=("api", "key-b83c46d8d404c3391a39dc7698a4c653"),
        data=data)
    if r.status_code != 200:
        raise Exception('Invalid Response from Mailgun: %r %r (%s)' % (
            r.status_code,
            r.text,
            json.dumps(data)))

def create(environ, db):
    data = interpret_post(environ)

    title, = data['title']
    title = re.sub("[^A-Za-z0-9 .,]", "-", title)
    title = re.sub("-+", "-", title)
    title = re.sub("^-*", "", title)
    title = re.sub("-*$", "", title)

    u_email, = data['email']
    if not data['day'] or len(data['day']) != len(data['nth']):
       raise Exception('invalid nth-day pairs')

    event_id = nonce()

    db.execute("INSERT into events (event_id, title, admin_email) "
                "VALUES (%s, %s, %s)",
                (event_id, title, u_email))

    for u_day, u_nth in zip(data['day'], data['nth']):
        db.execute("INSERT into recurrences (event_id, day, nth) "
                    "VALUES (%s, %s, %s)",
                    (event_id, u_day, u_nth))

    confirm_url = link('view', event_id)

    send_email(email, 'Confirm your standing event, %s' % title,
               '''\
To see your standing event, click:

    %s

If you didn't try to create a standing event, someone else must
have entered your email.  You can ignore this message.  Sorry
about that!
''' % confirm_url)

    return page('Create') + '''
Sent email to %s with instructions on how to confirm your event.
''' % email

def join(environ, db):
    data = interpret_post(environ)
    u_email, = data['email']
    u_event_id, = data['event_id']

    db.execute('SELECT title FROM events WHERE event_id = %s',
               (u_event_id, ))
    (title,), = db.fetchall()
    event_id = u_event_id

    member_nonce = nonce()

    db.execute('INSERT INTO members (event_id, email, nonce) '
               'VALUES (%s, %s, %s)', (event_id, u_email, member_nonce))

    confirm_url = link('confirm_join', member_nonce)

    send_email(u_email, "Confirm you'd like to join %s" % title, '''\
To join the standing event %s, click:

    %s

If you don't know what this is about, someone else must have entered
your email.  Sorry about that!
''' % (title, confirm_url))

    return page('Join') + '''
Sent email to %s with instructions on how to join %s.
''' % (html_escape(u_email), title)

def confirm_join(environ, db, u_member_nonce):
    db.execute('SELECT event_id, email FROM members WHERE nonce = %s',
               (u_member_nonce, ))
    (event_id, u_email), = db.fetchall()
    member_nonce = u_member_nonce

    db.execute('UPDATE members SET confirmed = true WHERE nonce = %s',
               (member_nonce, ))

    event_link = link('view', event_id)
    unsubscribe = link('unsubscribe', member_nonce)

    return page('Join Confirmed') + '''
%s will now receive email reminders about
<a href="%s">this standing event</a>.

<p>

To unsubscribe, <a href="%s">click here</a>.
''' % (html_escape(u_email), event_link, unsubscribe)

def unsubscribe(environ, db, u_member_nonce):
    db.execute('SELECT event_id, email FROM members WHERE nonce = %s',
               (u_member_nonce, ))
    (event_id, u_email), = db.fetchall()
    member_nonce = u_member_nonce

    db.execute('UPDATE members SET confirmed = false WHERE nonce = %s',
               (member_nonce, ))

    event_link = link('view', event_id)
    confirm_url = link('confirm_join', member_nonce)

    return page('Unsubscription Confirmed') + '''
%s will no longer receive email reminders about
<a href="%s">this standing event</a>.

<p>

To re-subscribe, <a href="%s">click here</a>.
''' % (html_escape(u_email), event_link, confirm_url)

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

def view(environ, db, u_event_id):
    db.execute('SELECT title, confirmed FROM events where event_id=%s',
               (u_event_id, ))
    (title, confirmed),  = db.fetchall()
    event_id = u_event_id
    if not confirmed:
        db.execute('UPDATE events SET confirmed=true WHERE event_id=%s',
                   (event_id, ))
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
            upcoming_dates.append(consider)

    upcoming = '<ul>%s</ul>' % '\n'.join(
        '<li><a href="%s">%s</a></li>' % (
            link('view_date', event_id, upcoming_date.strftime('%F')),
            upcoming_date.strftime('%F'))
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

    return page(title) + '''
<h1>%s</h1>
Happens on:
%s
Upcoming dates:
%s
Members:
%s
Calendar link: <a href="%s">ical</a><br><br>
<form action=../join method=post>
<input type=text name=email placeholder=Email></text>
<input type=hidden name=event_id value="%s"></input>
<input type=submit value=jooin>
''' % (
    title,
    recurrences,
    upcoming,
    members,
    calendar_link,
    event_id)

def view_date(environ, db, u_event_id, u_date):
    db.execute('SELECT title FROM events WHERE event_id=%s',
               (u_event_id, ))
    (title, ), = db.fetchall()
    event_id = u_event_id

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
    return page('%s on %s' % (title, date)) + '''
<h1>%s rsvps for %s</h1>
<ul>%s</ul>''' % (title, date, '\n'.join(rsvps))

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

                db.execute('SELECT email, nonce FROM members '
                           'WHERE confirmed = true AND event_id = %s',
                           (event_id, ))
                recipient_variables = dict(
                    (u_email, {'member_nonce': member_nonce})
                    for u_email, member_nonce in db.fetchall())

            day = advance.strftime('%A')
            send_emails(list(recipient_variables.keys()),
                        'Reminder: %s is this %s; rsvp?' % (title, day),
                        '''\
%s is this %s.  RSVP:

    %s''' % (title, day, link('rsvp', advance_date,
                              '%recipient.member_nonce%')),
                        recipient_variables)


def rsvp(environ, db, u_date, u_member_nonce):
    db.execute('SELECT event_id, email FROM members WHERE nonce = %s',
               (u_member_nonce, ))
    (event_id, u_email), = db.fetchall()
    member_nonce = u_member_nonce

    date = html_escape(u_date)
    if environ['CONTENT_LENGTH'] and int(environ['CONTENT_LENGTH']) > 0:
        data = interpret_post(environ)
        u_attending, = data['attending']

        if 'comment' in data:
            u_comment, = data['comment']
        else:
            u_comment = None

        db.execute('DELETE FROM rsvps WHERE event_id = %s and email = %s', (
            event_id, u_email))
        db.execute('INSERT INTO rsvps '
                   '(event_id, email, date, attending, comment) '
                   'VALUES (%s, %s, %s, %s, %s)', (
                       event_id, u_email, u_date, u_attending == 'yes',
                       u_comment))
        return page('RSVPd for %s' % date) + '''\
<h1>RSVPd %s for %s</h1>

See <a href="%s">others' RSVPs</a>
''' % ('Yes' if u_attending == 'yes' else 'No',
       date, link('view_date', event_id, date))

    else:
        db.execute('SELECT title FROM events WHERE event_id = %s',
                   (event_id, ))
        (title, ), = db.fetchall()
        return page('RSVP for %s on %s' % (title, date)) + '''\
<h1>RSVP for %s on %s</h1>
<form method=post>
<input type=radio name=attending value=yes>Yes</input><br>
<input type=radio name=attending value=no>No</input><br>
<br>
<input type=text name=comment placeholder=Comments></input><br>
<br>
<input type=submit value=RSVP></submit>
''' % (title, date)

def ical(environ, db, u_event_id):
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

def route(path, environ):
    with psycopg2.connect(
        "dbname='standing-events' user='%s' host='localhost'"
        " password='%s'" % (os.environ['DB_USER'],
                            os.environ['DB_PASS'])) as conn:
        with conn.cursor() as db:
            if path == '/':
                return index()

            if path == '/create':
                return create(environ, db)

            if path == '/join':
                return join(environ, db)

            if path.startswith('/view/'):
                event_id = path.split('/')[-1]
                return view(environ, db, event_id)

            if path.startswith('/view_date/'):
                event_id, date = path.split('/')[-2:]
                return view_date(environ, db, event_id, date)

            if path.startswith('/rsvp/'):
                date, member_nonce = path.split('/')[-2:]
                return rsvp(environ, db, date, member_nonce)

            if path.startswith('/ical/'):
                event_id = path.split('/')[-1]
                return ical(environ, db, event_id)

            if path.startswith('/confirm_join/'):
                member_nonce = path.split('/')[-1]
                return confirm_join(environ, db, member_nonce)

            if path.startswith('/unsubscribe/'):
                member_nonce = path.split('/')[-1]
                return unsubscribe(environ, db, member_nonce)

            return '%r not understood' % html_escape(path)

def die500(start_response, e):
    trb = '%s: %s\n\n%s' % (e.__class__.__name__, e, traceback.format_exc())
    start_response('500 Internal Server Error',
                   [('content-type', 'text/plain')])
    return trb

def application(environ, start_response):
    path = environ['PATH_INFO']
    if path.startswith(DEPLOY_LOCATION):
      try:
        output = route(path[len(DEPLOY_LOCATION):], environ)
        start_response('200 OK', [('content-type', 'text/html'),
                                  ('cache-control', 'no-cache')])
      except Exception as e:
        output = die500(start_response, e)
    else:
      output = 'not understood'

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
