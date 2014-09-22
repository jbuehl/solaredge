use solar;

drop table if exists inverters;
create table inverters (
    Date date,
    Time time,
    ID char(8),
    Uptime int,
    Intrvl int,
    Temp float,
    Eday float,
    Eint float,
    Vac float,
    Iac float,
    Freq float,
--    data9 char(8),
--    data10 char(8),
    Vdc float,
--    data12 char(8),
    Etot float,
--    data14 char(8),
--    data15 char(8),
--    data16 char(8),
--    data17 char(8),
    Pmax float,
--    data19 char(8),
--    data20 char(8),
--    data21 char(8),
--    data22 char(8),
    Pac float,
    unique index (date, time, id)
    );

drop table if exists optimizers;
create table optimizers (
    Date date,
    Time time,
    ID char(8),
    Inv char(8),
    Uptime int,
    Vmod float,
    Vopt float,
    Imod float,
    Eday float,
    Temp float,
    unique index (date, time, id)
    );

