import base64
import cgi
import Cookie
import datetime
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

class User:
    def __init__(self, u_email=None, u_name=None, nonce=None):
        self.u_email = u_email
        self.u_name = u_name
        self.nonce = nonce

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

def page(title, updest, user, body, hide_profile=False):
    if updest:
        up = '<a href="%s" id=up>&larr;</a>' % updest

    if hide_profile:
        profile = ''
    elif user.u_name or user.u_email:
        profile = '''\
%s
(<a href="%s">edit</a>,
 <a href="%s">log out</a>)''' % (
     display_name(user),
     link('profile'),
     link('logout', user.nonce))
    else:
        profile = '(<a href="%s">log in</a>)' % (
            link('login'))

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
  min-height: 100%%;
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
#profile {
  text-align: right;
  background-color: #CCC;
  padding: 10px;
  padding-top: 0px;
}
#up {
  background-color: #DFDFDF;
  padding: 10px;
  display: block;
  text-decoration: none;
  color: black;
}
#icalhelp {
  display: none;
  padding: 20px;
}
img {
  width: 100%%;
}
@media(min-width: 550px) {
  #content {
    width: 550px;
  }
}
</style>
<title>%s :: %s</title>
<div id=content>
<center><h1>%s</h1></center>
<div id=profile>%s</div>
%s
<div id=page>
%s
</div>
</div>''' % (
    APP_TITLE, title, title,
    '<div id=profile>%s</div>' % profile if profile else '',
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
  <option value=all>All</option>
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

def index(db, user, u_data):
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
        title = html_escape(re.sub("[^ -~]", "-", u_title))
        title = re.sub("-+", "-", title)
        title = re.sub("^-*", "", title)
        title = re.sub("-*$", "", title)

        u_form_email, = u_data['email']
        u_form_email, = u_data['name']
        if not u_data['day'] or len(u_data['day']) != len(u_data['nth']):
            raise Exception('invalid nth-day pairs')

        event_id = nonce()

        confirmed = user.u_email and (user.u_email == u_form_email)
        db.execute("INSERT INTO events (event_id, title, admin_email, confirmed) "
                   "VALUES (%s, %s, %s, %s)",
                   (event_id, title, u_form_email, bool(confirmed)))
        user_nonce = create_user(db, u_form_email, u_form_name)

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
    'event', event_id, id=user_nonce))

            top_note = '''\
<i>Sent email to %s with instructions on how to confirm
this event.</i><p>''' % html_escape(u_form_email)

    owned_section = ''
    following_section = ''
    if user.u_email:
        db.execute('SELECT event_id, title '
                   '  FROM events'
                   ' WHERE admin_email = %s'
                   '   AND confirmed'
                   ' ORDER BY title',
                   (user.u_email, ))
        owned_events = db.fetchall()
        if owned_events:
            owned_section = 'Hosting:<ul>%s</ul><p>' % '\n'.join(
                '<li><a href="%s">%s</a></li>' % (
                    link('event', event_id), title)
                for event_id, title in owned_events)
        owned_event_ids = set(event_id for event_id, _ in owned_events)

        db.execute('SELECT e.event_id, e.title '
                   '  FROM events AS e'
                   '  JOIN members AS m'
                   '    ON e.event_id = m.event_id'
                   ' WHERE m.email = %s'
                   '   AND m.confirmed'
                   ' ORDER BY e.title',
                   (user.u_email, ))
        following_events = db.fetchall()
        following_event_ids = set(event_id for event_id, _ in following_events)
        if following_event_ids - owned_event_ids:
            following_section = 'Following:<ul>%s</ul><p>' % '\n'.join(
                '<li><a href="%s">%s</a></li>' % (
                    link('event', event_id), title)
                for event_id, title in following_events
                if event_id not in owned_event_ids)

    return page('Schedule a Regular Event', updest=None, user=user,
                body='''
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
%s%s
''' % (top_note,
       title_note,
       selection_note,
       selection_partial().replace('{n}', '1'),
       email_note,
       ' value="%s"' % html_escape(user.u_email) if user.u_email else '',
       json.dumps(selection_partial()),
       owned_section,
       following_section))

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

def unsubscribe(db, u_event_id, u_user_nonce):
    db.execute('SELECT email, name FROM users WHERE nonce = %s',
               (u_user_nonce, ))
    (u_email, u_name), = db.fetchall()
    user = User(u_email=u_email, u_name=u_name, nonce=u_user_nonce)

    db.execute('SELECT confirmed FROM members '
               'WHERE email = %s AND event_id = %s',
               (user.u_email, u_event_id))
    response = db.fetchall()
    if response:
        (confirmed, ), = response
        event_id = u_event_id

        if confirmed:
            db.execute('DELETE FROM members '
                       'WHERE email = %s AND event_id = %s',
                       (user.u_email, u_event_id))
            event_link = link('event', event_id, id=user.nonce)

            return page('Unsubscription Confirmed', '/', user,
                        body='''
%s will no longer receive email reminders about
this regularly scheduled event.

<p>

To re-subscribe, <a href="%s">click here</a>.
''' % (html_escape(user.u_email), event_link))

    return page('Not Subscribed', '/', user, body='''\
%s was already not receiving email reminders about
this regularly scheduled event.
    ''' % html_escape(user.u_email))

def logout(db, user, u_user_nonce):
    if not user.nonce:
        return page('Not Logged In', '/', User(), body='Already not logged in.')
    elif user.nonce != u_user_nonce:
        return 'Invalid Link'

    return '''\
<meta http-equiv="set-cookie" content="id=''; Path=/">
<meta http-equiv="refresh" content="0; url=/">
'''

def matches(day_nth_pairs, consider):
    nth = {
        1: 'first',
        2: 'second',
        3: 'third',
        4: 'fourth',
        5: 'fifth'}[int((consider.day-1) / 7) + 1]

    day = {
        1: 'mondays',
        2: 'tuesdays',
        3: 'wednesdays',
        4: 'thursdays',
        5: 'fridays',
        6: 'saturdays',
        7: 'sundays'}[consider.isoweekday()]

    return (day, nth) in day_nth_pairs or (day, 'all') in day_nth_pairs

def create_user(db, u_email, u_name):
    db.execute('INSERT INTO users (email, name, nonce)'
               ' VALUES (%s, %s, %s)'
               ' ON CONFLICT DO NOTHING',
               (u_email, u_name, nonce()))
    db.execute('UPDATE users SET name = %s WHERE email = %s AND name IS NULL',
               (u_name, u_email))

    db.execute('SELECT nonce FROM users WHERE email = %s',
               (u_email, ))
    (user_nonce, ), = db.fetchall()
    return user_nonce

def display_name(user):
    if user.u_name:
        return html_escape('%s <%s>' % (user.u_name, user.u_email))
    else:
        return html_escape(user.u_email)

def display_name_public(user):
    if user.u_name:
        return html_escape(user.u_name)
    else:
        return html_escape(user.u_email)

def event(db, u_event_id, user, data):
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

    is_member = False
    if user.u_email:
        db.execute('SELECT confirmed FROM members '
                   ' WHERE event_id = %s and email = %s',
                   (event_id, user.u_email))
        response = db.fetchall()
        if response:
            (confirmed, ), = response
            if not confirmed:
                db.execute('UPDATE members SET confirmed = true '
                           ' WHERE event_id = %s and email = %s',
                           (event_id, user.u_email))
                receive = 'will now receive'
            else:
                receive = 'receive'

            is_member = True
            top_note = '''\
<i>You %s email reminders for this event; <a href="%s">unsubscribe</a></i>.<p>
''' % (receive,
       link('unsubscribe', event_id, user.nonce))


    if data:
        u_form_email, = data['email']
        u_form_name, = data['name']

        confirmed = user.u_email and (user.u_email == u_form_email)

        user_nonce = create_user(db, u_form_email, u_form_name)

        db.execute('INSERT INTO members (event_id, email, confirmed) '
                   'VALUES (%s, %s, %s) ON CONFLICT DO NOTHING',
                   (event_id, u_form_email, bool(confirmed)))

        if confirmed:
            top_note = '''\
<i>You will now receive email reminders for this event; <a href="%s">unsubscribe</a></i><p>''' % (
    link('unsubscribe', event_id, user_nonce))
        else:
            confirm_url = link('event', event_id, id=user_nonce)

            if user.u_email:
                msg = "%s has invited you to join" % display_name_public(user)
            else:
                msg = "Confirm you'd like to join"
            send_email(u_form_email, "%s %s" % (msg, title), '''\
To join the regularly scheduled event %s, click:

    %s

If you don't know what this is about, someone else must have entered
your email.  Sorry about that!
''' % (title, confirm_url))

            top_note = '''\
<i>Sent email to %s with a link to confirm.</i><p>
''' % html_escape(u_form_email)

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

    db.execute('SELECT u.email, u.name '
               'FROM members AS m '
               'JOIN users AS u '
               'ON m.email = u.email '
               'WHERE m.event_id=%s AND m.confirmed=true '
               'ORDER BY u.name, u.email ASC', (event_id, ))
    member_emails = list((u_email, u_name) for (u_email, u_name) in db.fetchall())
    if member_emails:
        members = '<ul>%s</ul>' % '\n'.join(
            '<li>%s</li>' % display_name_public(
                User(u_email=u_email, u_name=u_name)) for
            (u_email, u_name) in member_emails)
    else:
        members = 'currently no one<br><br>'

    calendar_link = link('ical', event_id)

    db.execute('SELECT u.email, u.name'
               ' FROM events AS e'
               ' JOIN users AS u'
               ' ON u.email = e.admin_email'
               ' WHERE e.event_id = %s',
               (event_id, ))
    (u_host_email, u_host_name), = db.fetchall()

    cancel = ''
    if user.u_email and user.u_email == u_host_email:
        cancel = '''\
<br><br>
<form action="%s" method=post>
<input name=user_nonce type=hidden value=%s></text>
<input name=confirm type=hidden value=false></text>
<input type=submit value="cancel event">
</form>''' % (link('confirm_cancel', event_id),
              user.nonce)

    join_or_invite = '''\
<p>
<form method=post>
<input type=text name=name placeholder=Name%s></text><br>
<input type=text name=email placeholder=Email%s></text>
<input type=submit value=%s>
</form>
<p>''' % (
    (' value="%s"' % html_escape(user.u_email)) if user.u_email and not is_member else '',
    (' value="%s"' % html_escape(user.u_name)) if user.u_name and not is_member else '',
    'invite' if is_member else 'join')

    return page(title, '/', user, body='''
%s
%sHappens on:
%s
Upcoming dates:
%s
Members:
%s
<p>
Host: %s
<p>
Calendar link: <a href="%s">ical</a>
<span id=showicalhelp>(<a href='#' onclick='icalhelp(); return false;'>help</a>)</span>
<div id=icalhelp>
To add to Google calendar:
<ol>
    <li>Next to "other calendars" click the down arrow, then "add by url":
    <br>
    <img src="/images/other-calendars.png">

    <li>Paste <tt><a href="%s">%s</a></tt> into the url field and click "add calendar".
    <br>
    <img src="/images/add-by-url.png">
</ol>
</div>
<script>
function icalhelp() {
  document.getElementById('icalhelp').style.display = 'block';
  document.getElementById('showicalhelp').style.display = 'none';
}
</script>
%s
''' % (
    top_note,
    join_or_invite,
    recurrences,
    upcoming,
    members,
    display_name(User(u_email=u_host_email, u_name=u_host_name)),
    calendar_link,
    calendar_link,
    html_escape(calendar_link),
    cancel))

def send_emails_for_today(*emails):
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

                cmd = ('SELECT u.email, u.nonce '
                       ' FROM members AS m'
                       ' JOIN users AS u'
                       '   ON m.email = u.email'
                       ' WHERE m.confirmed = true'
                       '   AND m.event_id = %s'
                       '   AND u.email NOT IN ('
                       '   SELECT email FROM rsvps'
                       '    WHERE event_id = %s'
                       '      AND date = %s)')
                if emails:
                    db.execute(cmd + ' AND u.email in %s', (
                        event_id, event_id, advance_date, emails))
                else:
                    db.execute(cmd, (event_id, event_id, advance_date))

                recipient_variables = dict(
                    (u_email, {'user_nonce': user_nonce})
                    for u_email, user_nonce in db.fetchall())
                if recipient_variables:
                    day = advance.strftime('%A')
                    send_emails(list(recipient_variables.keys()),
                                'Reminder: %s is this %s; rsvp?' % (
                                    title, day),
                                '''\
%s is this %s.  RSVP:

    %s''' % (title, day, link(
        'event', event_id, advance_date,
        id='%recipient.user_nonce%')),
                                recipient_variables)


def event_date(db, u_event_id, u_date, user, u_data):
    date = html_escape(u_date)
    top_note = ''

    db.execute('SELECT title FROM events WHERE event_id = %s',
               (u_event_id, ))
    (title,), = db.fetchall()
    event_id = u_event_id

    is_member = False
    if user.u_email:
        db.execute('SELECT confirmed FROM members'
                   ' WHERE event_id = %s AND email = %s',
                   (event_id, user.u_email))
        response = db.fetchall()
        if response:
            (confirmed, ), = response
            if confirmed:
                is_member = True

        if is_member and u_data:
            u_attending, = u_data['attending']

            if 'comment' in u_data:
                u_comment, = u_data['comment']
            else:
                u_comment = None

            db.execute('DELETE FROM rsvps WHERE event_id = %s and email = %s', (
                event_id, user.u_email))
            db.execute('INSERT INTO rsvps '
                       '(event_id, email, date, attending, comment) '
                       'VALUES (%s, %s, %s, %s, %s)', (
                           event_id, user.u_email, u_date, u_attending == 'yes',
                           u_comment))
            top_note = '<i>RSVPd %s</i><p>' % (
                'Yes' if u_attending == 'yes' else 'No')

    db.execute('SELECT attending, comment FROM rsvps '
               ' WHERE event_id = %s'
               '   AND email = %s'
               '   AND date = %s',
               (event_id, user.u_email, u_date))
    results = db.fetchall()
    if results:
        (attending, _), = results
    else:
        attending = None

    rsvp_form = '''\
<form method=post>
<input type=radio name=attending value=yes%s>Yes</input><br>
<input type=radio name=attending value=no%s>No</input><br>
<br>
<input type=text name=comment placeholder=Comments></input><br>
<br>
<input type=submit value=RSVP></submit>
''' % (' checked' if attending is True else '',
       ' checked' if attending is False else '')

    db.execute('SELECT title FROM events WHERE event_id=%s',
               (event_id, ))
    (title, ), = db.fetchall()

    db.execute('SELECT u.email, r.attending, r.comment, u.name'
               ' FROM rsvps AS r'
               ' JOIN users AS u'
               ' ON r.email = u.email'
               ' WHERE r.event_id=%s AND r.date=%s '
               ' ORDER by u.email ASC', (event_id, u_date))
    rsvps = ['<li><p>%s: %s%s' % (
        display_name_public(User(u_email=u_member_email,
                                 u_name=u_member_name)),
        'Yes' if attending else 'No',
        ('<blockquote><i>%s</i></blockquote>' % html_escape(u_comment)
         if u_comment else ''))
             for u_member_email, attending, u_comment, u_member_name in db.fetchall()]
    date = html_escape(u_date)

    if rsvps:
        current_rsvps = '<ul>%s</ul>' % '\n'.join(rsvps)
    else:
        current_rsvps = 'No RSVPs yet.'

    return page('%s: %s' % (title, date.replace('-', '&#x2011;')),
                link('event', event_id),
                user, body='%s%s<p>%s' % (
        top_note,
        rsvp_form if is_member else '',
        current_rsvps))

def confirm_cancel(db, u_event_id, user, u_data):
    if u_data and u_data['user_nonce'] == [user.nonce]:
        db.execute('SELECT admin_email FROM events'
                   ' WHERE admin_email = %s'
                   '   AND event_id = %s',
                   (user.u_email, u_event_id))
        if db.fetchall():
            event_id = u_event_id
            if u_data['confirm'] == ['true']:
                db.execute('DELETE FROM members WHERE event_id = %s',
                           (event_id, ))
                db.execute('DELETE FROM recurrences WHERE event_id = %s',
                           (event_id, ))
                db.execute('DELETE FROM rsvps WHERE event_id = %s',
                           (event_id, ))
                db.execute('DELETE FROM events WHERE event_id = %s',
                           (event_id, ))
                return page('Event Deleted', '/', user, body='')
            else:
                return page('Really Delete?', link('event', event_id),
                            user, body='''\
Really delete this event?  This cannot be undone.
<p>
<form action="%s">
<input type=submit value="no, keep event">
</form>
<form method=post>
<input name=user_nonce type=hidden value=%s></text>
<input name=confirm type=hidden value=true></text>
<input type=submit value="yes, cancel event">
</form>''' % (link('event', event_id), user_nonce))

    return page('Access Denied', link('event', html_escape(u_event_id)),
                user, body='')

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
                    u_user_nonce, = query['id']
                    db.execute('SELECT nonce FROM users WHERE nonce = %s',
                               (u_user_nonce, ))
                    if db.fetchall():
                        if u_path.startswith('/'):
                            u_path = u_path[1:]
                        return '''\
<meta http-equiv="set-cookie" content="id=%s; Path=/">
<meta http-equiv="refresh" content="0; url=%s">
''' % (u_user_nonce, link(html_escape(u_path)))

            user = User()
            if 'HTTP_COOKIE' in environ:
                cookies = Cookie.SimpleCookie(environ['HTTP_COOKIE'])
                if 'id' in cookies:
                    u_user_nonce = cookies['id'].value
                    db.execute('SELECT email, name FROM users WHERE nonce = %s',
                               (u_user_nonce, ))
                    results = db.fetchall()
                    if results:
                        (u_email, u_name), = results
                        user = User(u_email=u_email, u_name=u_name, nonce=u_user_nonce)

            if (environ['CONTENT_LENGTH'] and
                int(environ['CONTENT_LENGTH']) > 0):

                u_data = cgi.parse_qs(
                    environ['wsgi.input'].read(
                        int(environ['CONTENT_LENGTH'])))
            else:
                u_data = {}

            if u_path in ['', '/']:
                return index(db, user, u_data)

            if u_path.startswith('/event/'):
                u_rest = u_path[len('/event/'):]
                u_pieces = u_rest.split('/')
                if len(u_pieces) == 1:
                    u_event_id, = u_pieces
                    return event(db, u_event_id, user, u_data)
                elif len(u_pieces) == 2:
                    u_event_id, u_date = u_pieces
                    return event_date(
                        db, u_event_id, u_date, user, u_data)
                else:
                    return '%r not understood' % html_escape(u_path)

            if u_path.startswith('/ical/'):
                u_event_id = u_path.split('/')[-1]
                return ical(db, u_event_id)

            if u_path.startswith('/unsubscribe/'):
                u_rest = u_path[len('/unsubscribe/'):]
                u_event_id, u_user_nonce = u_rest.split('/')
                return unsubscribe(db, u_event_id, u_user_nonce)

            if u_path.startswith('/logout/'):
                u_rest = u_path[len('/logout/'):]
                u_user_nonce, = u_rest.split('/')
                return logout(db, user,  u_user_nonce)

            if u_path.startswith('/login'):
                return login(db, user, u_data)

            if u_path.startswith('/confirm_cancel/'):
                u_rest = u_path[len('/confirm_cancel/'):]
                u_event_id, = u_rest.split('/')
                return confirm_cancel(
                    db, u_event_id, user, u_data)

            return '%r not understood' % html_escape(u_path)

def login(db, user, u_data):
    top_note = ''
    if u_data and u_data['email']:
        u_email, = u_data['email']
        db.execute('SELECT nonce'
                   ' FROM users'
                   ' WHERE email=%s',
                   (u_email, ))
        results = db.fetchall()
        if results:
            (user_nonce, ),  = results
            send_email(u_email, 'Log into regularlyscheduled.com', '''\
To log into regularlyscheduled.com, click:

    %s

If you weren't trying to log in, someone else must have entered your email.
You can ignore this message.  Sorry about that!''' % (
    link('', id=user_nonce)))

            top_note = '<i>email sent to %s with login instructions</i><p>' % (
                html_escape(u_email))
        else:
            top_note = '<i>address not recognized</i><p>'

    return page('Log in', '/', user, hide_profile=True, body='''\
%s
<form method=post>
<input name=email placeholder=Email></input>
<input type=submit value="Send Login Email">
</form>''' % (top_note))


def die500(start_response, e):
    trb = '%s: %s\n\n%s' % (e.__class__.__name__, e, traceback.format_exc())
    start_response('500 Internal Server Error',
                   [('content-type', 'text/plain')])
    return trb

def application(environ, start_response):
    u_path = environ['PATH_INFO']
    try:
        output = route(u_path, environ)
        content_type = 'text/html'
        if u_path.startswith('/ical/'):
            content_type = 'text/calendar'
        start_response('200 OK', [('content-type', content_type),
                                  ('cache-control', 'no-cache')])
    except Exception as e:
        output = die500(start_response, e)

    return (output.encode('utf8'), )

def run_debug(path):
    def start_response(status_code, headers):
        print(status_code)
        for k, v in headers:
            print('%s: %s' % (k, v))
        print('')
    environ = {'PATH_INFO': path}
    for x in application(environ, start_response):
        for l in x.split(b'\n'):
            print(l)

if __name__ == '__main__':
    args = sys.argv[1:]
    if args:
        if len(args) == 1 and '@' not in args[0]:
            run_debug(args[0])
        else:
            send_emails_for_today(*args)
    else:
        send_emails_for_today()
