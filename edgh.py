import mysql-connector-python
db = mysql.connector.connect(
    host="localhost",
    user="cicada",
    password="Qaz19915126.",
    database="yourdatabase"
)
cursor= db.cursor()
cursor.execute("SELECT * FROM your_table")
results = cursor.fetchall()
for row in results:
    print(row)