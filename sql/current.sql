use solar;
-- select round(sum(eday)/1000,3) Etoday, round(sum(etot)/1000,3) Etotal, round(avg(temp)*9/5+32,0) Temp from inverters,
select inverters.* from inverters,
	(select date, max(time) time, id from inverters
		where date = curdate()
		group by id) max
	where inverters.date = max.date and inverters.time = max.time
