use solar;
load data local infile '/root/solar/inv.csv' into table inverters fields terminated by ',';
load data local infile '/root/solar/opt.csv' into table optimizers fields terminated by ',';
