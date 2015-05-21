drop table if exists site;
create table site select inv.eday Eday, mon.emon Emonth, yr.eyr Eyear, inv.etot Elifetime, inv.temp Tinv, opt.temp Topt from
	(select sum(Eday) eday, sum(Etot) etot, avg(Temp) temp from invstate) inv
	join
	(select avg(Temp) temp from optstate) opt
	join
	(select sum(eday.Eday) emon from
		(select date, id, max(eday) eday from inverters 
			where month(date) = month(now())
			group by date, id) eday) mon
	join
	(select sum(eday.Eday) eyr from
		(select date, id, max(eday) eday from inverters 
			where year(date) = year(now())
			group by date, id) eday) yr;
