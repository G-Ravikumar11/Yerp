-- Only if SETUP.bat could not give the sync access by itself. Run ONCE in SQL Server Management Studio, connected as
-- an administrator. Use ONE of the two ways, and change the database name if it is not etimetracklite.

-- 1. A SQL login that can only READ the attendance database (the server must allow "SQL Server and Windows
--    Authentication"). Change the password, and put it in config.ini with user = yerp_reader.
USE [master];
CREATE LOGIN [yerp_reader] WITH PASSWORD = N'CHANGE-THIS-PASSWORD', CHECK_POLICY = OFF;
GO
USE [etimetracklite];
CREATE USER [yerp_reader] FOR LOGIN [yerp_reader];
EXEC sp_addrolemember 'db_datareader', 'yerp_reader';
GO

-- 2. Or no password at all: let the computer's SYSTEM account (which the every-minute task runs as) read it, and leave
--    user and password empty in config.ini.
-- USE [master]; IF NOT EXISTS (SELECT 1 FROM sys.server_principals WHERE name = N'NT AUTHORITY\SYSTEM') CREATE LOGIN [NT AUTHORITY\SYSTEM] FROM WINDOWS;
-- USE [etimetracklite]; CREATE USER [NT AUTHORITY\SYSTEM] FOR LOGIN [NT AUTHORITY\SYSTEM]; EXEC sp_addrolemember 'db_datareader', N'NT AUTHORITY\SYSTEM';
