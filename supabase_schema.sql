create table if not exists extracted_data (
    id uuid primary key default gen_random_uuid(),
    image_name text not null,
    extracted_text text,
    created_at timestamptz not null default now()
);

alter table extracted_data add column if not exists rider_id text;

create table if not exists rider_stats (
    rider_id text primary key,
    complete_hours text,
    complete_order text,
    installments text,
    wallet text,
    updated_at timestamptz not null default now()
);

alter table rider_stats add column if not exists stat_date date not null default current_date;
alter table rider_stats drop constraint if exists rider_stats_pkey;
alter table rider_stats add primary key (rider_id, stat_date);

alter table rider_stats add column if not exists driver_name text;
alter table rider_stats add column if not exists phone text;
alter table rider_stats add column if not exists zone text;

create table if not exists users (
    id uuid primary key default gen_random_uuid(),
    username text not null unique,
    password_hash text not null,
    created_at timestamptz not null default now()
);

create table if not exists digit_templates (
    id uuid primary key default gen_random_uuid(),
    label text not null,
    canvas_data text not null,
    created_at timestamptz not null default now()
);
create index if not exists digit_templates_label_idx on digit_templates (label);
