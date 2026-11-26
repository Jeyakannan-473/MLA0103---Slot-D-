-- MySQL setup for the Welfare Scheme Navigator.
-- 1) Run this file to create the database and a dedicated user (change the password!).
-- 2) Tables are created from the SQLAlchemy models by:   flask --app run.py init-db
--    (or generate the full DDL into this file with:      python scripts/export_schema.py)

CREATE DATABASE IF NOT EXISTS welfare_navigator CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS 'welfare_user'@'localhost' IDENTIFIED BY 'CHANGE_THIS_PASSWORD';
GRANT ALL PRIVILEGES ON welfare_navigator.* TO 'welfare_user'@'localhost';
FLUSH PRIVILEGES;
