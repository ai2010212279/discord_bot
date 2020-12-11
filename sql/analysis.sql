CREATE TABLE IF NOT EXISTS analysis (
msg_id bigint not null primary key,
content text not null,
user_name varchar(255) not null,
user_id bigint not null,
bot tinyint default 0,
date_time datetime,
channel varchar(255),
channel_id bigint,
keyword varchar(255)
);
