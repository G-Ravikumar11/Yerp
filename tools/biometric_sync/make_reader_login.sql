-- Run ONCE in SQL Server Management Studio, connected as an administrator.
-- It makes a login that can only READ the attendance database. Change the password before running.
USE [master];
CREATE LOGIN [yerp_reader] WITH PASSWORD = N'CHANGE-THIS-PASSWORD', CHECK_POLICY = OFF;
GO
USE [etimetracklite];
CREATE USER [yerp_reader] FOR LOGIN [yerp_reader];
ALTER ROLE [db_datareader] ADD MEMBER [yerp_reader];
GO
