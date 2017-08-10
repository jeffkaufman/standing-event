Standing Events
===============

The code behind regularlyscheduled.com

Dependencies:

    sudo apt-get install python-psycopg2

Environment variables:

    DB_USER
    DB_PASS
    MAILGUN_API_KEY

A service file would be like:

    [Unit]
    Description=uWSGI standing event

    [Service]
    ExecStart=/usr/bin/uwsgi --socket :7093 --plugin /usr/lib/uwsgi/plugins/python_plugin.so --wsgi-file /home/jefftk/standing-event/standing_event.py
    Restart=always
    KillSignal=SIGQUIT
    Type=notify
    NotifyAccess=all

    Environment=DB_USER=[...]
    Environment=DB_PASS=[...]
    Environment=MAILGUN_API_KEY=[...]

    [Install]
    WantedBy=multi-user.target

Database setup:

```
sudo apt-get install postgresql postgresql-contrib
sudo -i -u postgres
postgres@host:~$ createdb standing-events
postgres@host:~$ psql
postgres=# \c standing-events
postgres=# CREATE TABLE events (
   event_id char(12) primary key not null,
   title varchar(255) not null,
   admin_email varchar(255) not null,
   when_created timestamp default current_timestamp not null,
   confirmed bool default false not null);
postgres=# CREATE TABLE recurrences (
   event_id char(12) not null references events(event_id),
   day varchar(20) not null,
   nth varchar(20) not null
   PRIMARY KEY(event_id, day, nth));
postgres=# CREATE INDEX on recurrences (event_id);
postgres=# CREATE TABLE users (
   email varchar(255) primary key not null,
   nonce char(12) not null);
postgres=# CREATE INDEX on users (nonce);
postgres=# CREATE TABLE members (
   event_id char(12) not null references events(event_id),
   email varchar(255) not null,
   confirmed bool not null default false,
   PRIMARY KEY(event_id, email));
postgres=# CREATE INDEX on members (event_id);
postgres=# CREATE INDEX on members (nonce);
postgres=# CREATE TABLE rsvps (
   event_id char(12) not null references events(event_id),
   email varchar(255) not null,
   date date not null,
   attending bool,
   comment varchar(1024),
   PRIMARY KEY(event_id, email, date));
postgres=# CREATE INDEX on rsvps (event_id, date);
postgres=# CREATE USER $DB_USER PASSWORD '$DB_PASS';
postgres=# GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO $DB_USER;
```
