select Name, attributes.id ID, round(avg(Daily_Output), 0) Pavg, round(temp*9/5+32, 0) Temp, Array, round(tilt, 1) Tilt, Azimuth 
	from (select date, id, max(eday) Daily_Output, avg(temp) temp 
		from optimizers 
		group by date, id
		) blah 
	inner join attributes on blah.id = attributes.id 
	group by id
	order by Pavg desc;
