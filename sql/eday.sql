use solar;
select 
    day.date Date, round(sum(day.eday)/1000, 3) Eday, round(avg(day.temp)*9/5+32, 0)
    from (select date, id, max(eday) eday, temp
        from inverters 
        group by date, id) day 
    group by day.date;
