from os import path

DEFAULT_PHONE_PATTERN = r"^\+?\(?\d{2,4}\)?[\s.-]?\d{3,4}[\s.-]?\d{3,4}$"
DEFAULT_NAME_PATTERN = r"^[A-Za-z\-\']{2,20}(\s[A-Za-z]{1,20}){0,3}\s[A-Za-z]{2,20}$"
DATABASE_PATH = path.join("data","app_database.db")
NO_SELECTED_CUSTOMER_WARNING = """<b>Error: you must select a customer first...</b>

<code>/search query</code>*

 query* : <b>name</b>/<b>phone</b>
 Note: <code>/search</code> will display all your customers
"""
welcome_msg = """
<b>Welcome to the Paytrack bot</b>
<i>Select an option to continue.</i>

<blockquote>
<b>Updates available</b>
Profile • Settings
</blockquote>

<a href="https://example.com/dashboard">Open dashboard</a>
<b>Welcome to the platform</b>
<i>Select an option to continue.</i>

<blockquote>
「 ✦ Besho vergjel jikabohboj ✦ 」

<b>💸 <code>$500.0</code>
                            12:57 PM • 14 Nov 2025</b>

<b>💰 <code>$5.0</code>
                            12:57 PM • 14 Nov 2025</b>
 
<b>💸 <code>$500.0</code>
                            12:57 PM • 14 Nov 2025</b>
 
<b>💰 <code>$5.0</code>
                            12:57 PM • 14 Nov 2025</b>

</blockquote>


<a href="https://example.com/dashboard">Open dashboard</a>

"""