select sum(a.eday) from (select date, id, max(eday) eday from optimizers where id in ("1016AB88", "1016B2BB") group by date, id) a;
