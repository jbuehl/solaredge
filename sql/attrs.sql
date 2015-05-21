use solar;
drop table if exists invattrs;
create table invattrs (
    name char(8),
    id char(8),
    primary key(id)
    );
insert into invattrs values ("inv1", "7F104920");
insert into invattrs values ("inv2", "7F104A16");

drop table if exists optattrs;
create table optattrs (
    name char(8),
    id char(8),
    array char(8),
    tilt float,
    azimuth float,
    Pmax float,
    ckdigit char(2),
    primary key (id)
    );
insert into optattrs values ("opt01", "100F7220", "south", 18.5, 180, 300, "B1");
insert into optattrs values ("opt02", "100F746B", "south", 18.5, 180, 300, "FE");
insert into optattrs values ("opt03", "100F74DB", "south", 18.5, 180, 300, "6E");
insert into optattrs values ("opt04", "100F72C1", "south", 18.5, 180, 300, "52");
insert into optattrs values ("opt05", "100F7333", "south", 18.5, 180, 300, "C5");
insert into optattrs values ("opt06", "100F7335", "south", 18.5, 180, 300, "C7");
insert into optattrs values ("opt07", "100F7401", "south", 18.5, 180, 300, "94");
insert into optattrs values ("opt08", "100F74A0", "west", 18.5, 270, 300, "33");
insert into optattrs values ("opt09", "100F714E", "west", 18.5, 270, 300, "DE");
insert into optattrs values ("opt10", "100E32F9", "west", 18.5, 270, 300, "49");
insert into optattrs values ("opt11", "100F7195", "west", 18.5, 270, 300, "25");
insert into optattrs values ("opt12", "100F6FC5", "west", 18.5, 270, 300, "53");
insert into optattrs values ("opt13", "100F721E", "west", 18.5, 270, 300, "AF");
insert into optattrs values ("opt14", "100E3326", "west", 18.5, 270, 300, "77");
insert into optattrs values ("opt15", "100E3520", "west", 18.5, 270, 300, "73");
insert into optattrs values ("opt16", "100F74B7", "west", 18.5, 270, 300, "4A");
insert into optattrs values ("opt17", "100F755D", "west", 18.5, 270, 300, "F1");
insert into optattrs values ("opt18", "100E34EC", "west", 18.5, 270, 300, "3E");
insert into optattrs values ("opt19", "100F747C", "west", 18.5, 270, 300, "0F");
insert into optattrs values ("opt20", "100F7408", "west", 18.5, 270, 300, "9B");
insert into optattrs values ("opt21", "100E3313", "west", 18.5, 270, 300, "64");
insert into optattrs values ("opt22", "100F707C", "west", 18.5, 270, 300, "0B");
insert into optattrs values ("opt23", "100F7118", "west", 18.5, 270, 300, "A8");
insert into optattrs values ("opt24", "100F74D9", "west", 18.5, 270, 300, "6C");
insert into optattrs values ("opt25", "100F719B", "west", 18.5, 270, 300, "2B");
insert into optattrs values ("opt26", "100F71F9", "west", 18.5, 270, 300, "89");
insert into optattrs values ("opt27", "100F7237", "west", 18.5, 270, 300, "C8");
insert into optattrs values ("opt28", "100F74C6", "west", 18.5, 270, 300, "59");
insert into optattrs values ("opt29", "100F743D", "west", 18.5, 270, 300, "D0");
insert into optattrs values ("opt30", "100E3325", "west", 18.5, 270, 300, "76");
insert into optattrs values ("opt31", "100F71E5", "west", 18.5, 270, 300, "75");
insert into optattrs values ("opt32", "100F7255", "west", 18.5, 270, 300, "E6");
insert into optattrs values ("opt33", "1016AB88", "extra", 27, 180, 300, "59");
insert into optattrs values ("opt34", "1016B2BB", "extra", 27, 180, 300, "93");

drop table if exists invstate;
create table invstate like inverters;
insert into invstate values ("", "", "7F104920", 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0);
insert into invstate values ("", "", "7F104A16", 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0);

drop table if exists optstate;
create table optstate like optimizers;
insert into optstate values ("", "", "100E32F9", "", 0, 0, 0, 0, 0, 0);
insert into optstate values ("", "", "100E3313", "", 0, 0, 0, 0, 0, 0);
insert into optstate values ("", "", "100E3325", "", 0, 0, 0, 0, 0, 0);
insert into optstate values ("", "", "100E3326", "", 0, 0, 0, 0, 0, 0);
insert into optstate values ("", "", "100E34EC", "", 0, 0, 0, 0, 0, 0);
insert into optstate values ("", "", "100E3520", "", 0, 0, 0, 0, 0, 0);
insert into optstate values ("", "", "100F6FC5", "", 0, 0, 0, 0, 0, 0);
insert into optstate values ("", "", "100F707C", "", 0, 0, 0, 0, 0, 0);
insert into optstate values ("", "", "100F7118", "", 0, 0, 0, 0, 0, 0);
insert into optstate values ("", "", "100F714E", "", 0, 0, 0, 0, 0, 0);
insert into optstate values ("", "", "100F7195", "", 0, 0, 0, 0, 0, 0);
insert into optstate values ("", "", "100F719B", "", 0, 0, 0, 0, 0, 0);
insert into optstate values ("", "", "100F71E5", "", 0, 0, 0, 0, 0, 0);
insert into optstate values ("", "", "100F71F9", "", 0, 0, 0, 0, 0, 0);
insert into optstate values ("", "", "100F721E", "", 0, 0, 0, 0, 0, 0);
insert into optstate values ("", "", "100F7220", "", 0, 0, 0, 0, 0, 0);
insert into optstate values ("", "", "100F7237", "", 0, 0, 0, 0, 0, 0);
insert into optstate values ("", "", "100F7255", "", 0, 0, 0, 0, 0, 0);
insert into optstate values ("", "", "100F72C1", "", 0, 0, 0, 0, 0, 0);
insert into optstate values ("", "", "100F7333", "", 0, 0, 0, 0, 0, 0);
insert into optstate values ("", "", "100F7335", "", 0, 0, 0, 0, 0, 0);
insert into optstate values ("", "", "100F7401", "", 0, 0, 0, 0, 0, 0);
insert into optstate values ("", "", "100F7408", "", 0, 0, 0, 0, 0, 0);
insert into optstate values ("", "", "100F743D", "", 0, 0, 0, 0, 0, 0);
insert into optstate values ("", "", "100F746B", "", 0, 0, 0, 0, 0, 0);
insert into optstate values ("", "", "100F747C", "", 0, 0, 0, 0, 0, 0);
insert into optstate values ("", "", "100F74A0", "", 0, 0, 0, 0, 0, 0);
insert into optstate values ("", "", "100F74B7", "", 0, 0, 0, 0, 0, 0);
insert into optstate values ("", "", "100F74C6", "", 0, 0, 0, 0, 0, 0);
insert into optstate values ("", "", "100F74D9", "", 0, 0, 0, 0, 0, 0);
insert into optstate values ("", "", "100F74DB", "", 0, 0, 0, 0, 0, 0);
insert into optstate values ("", "", "100F755D", "", 0, 0, 0, 0, 0, 0);
insert into optstate values ("", "", "1016AB88", "", 0, 0, 0, 0, 0, 0);
insert into optstate values ("", "", "1016B2BB", "", 0, 0, 0, 0, 0, 0);
