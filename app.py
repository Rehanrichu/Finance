import os

from cs50 import SQL
from flask import Flask, flash, redirect, render_template, request, session
from flask_session import Session
from werkzeug.security import check_password_hash, generate_password_hash

from helpers import apology, login_required, lookup, usd

# Configure application
app = Flask(__name__)

# Custom filter
app.jinja_env.filters["usd"] = usd

# Configure session to use filesystem (instead of signed cookies)
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

# Configure CS50 Library to use SQLite database
db = SQL("sqlite:///finance.db")


@app.after_request
def after_request(response):
    """Ensure responses aren't cached"""
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Expires"] = 0
    response.headers["Pragma"] = "no-cache"
    return response


@app.route("/")
@login_required
def index():
    # Sum up holdings
    rows = db.execute(
        "SELECT symbol, SUM(shares) AS shares FROM transactions WHERE user_id = ? GROUP BY symbol HAVING shares > 0",
        session["user_id"]
    )

    holdings = []
    holdings_total = 0.0

    for row in rows:
        symbol = row["symbol"]
        shares = row["shares"]
        quote = lookup(symbol)
        price = quote["price"]
        total = price * shares
        holdings.append({
            "symbol": symbol,
            "name": quote["name"],
            "shares": shares,
            "price": price,
            "total": total
        })
        holdings_total += total

    user = db.execute("SELECT cash FROM users WHERE id = ?", session["user_id"])[0]
    cash = user["cash"]
    grand_total = cash + holdings_total

    return render_template("index.html", holdings=holdings, cash=cash, grand_total=grand_total)


@app.route("/buy", methods=["GET", "POST"])
@login_required
def buy():
    if request.method == "POST":
        symbol = request.form.get("symbol")
        shares = request.form.get("shares")

        if not symbol:
            return apology("must provide symbol", 400)
        quote = lookup(symbol)
        if not quote:
            return apology("invalid symbol", 400)

        if not shares or not shares.isdigit() or int(shares) <= 0:
            return apology("shares must be a positive integer", 400)
        shares = int(shares)

        rows = db.execute("SELECT cash FROM users WHERE id = ?", session["user_id"])
        cash = rows[0]["cash"]
        cost = quote["price"] * shares

        if cash < cost:
            return apology("can't afford", 400)

        # Record transaction
        db.execute("INSERT INTO transactions (user_id, symbol, shares, price) VALUES (?, ?, ?, ?)",
                   session["user_id"], quote["symbol"], shares, quote["price"])

        # Update user's cash
        db.execute("UPDATE users SET cash = ? WHERE id = ?", cash - cost, session["user_id"])

        return redirect("/")
    else:
        return render_template("buy.html")


@app.route("/history")
@login_required
def history():
    rows = db.execute(
        "SELECT symbol, shares, price, transacted FROM transactions WHERE user_id = ? ORDER BY transacted DESC",
        session["user_id"]
    )
    # Optionally augment rows with company name via lookup when rendering template
    for r in rows:
        r["name"] = lookup(r["symbol"])["name"]
    return render_template("history.html", rows=rows)


@app.route("/login", methods=["GET", "POST"])
def login():
    """Log user in"""

    # Forget any user_id
    session.clear()

    # User reached route via POST (as by submitting a form via POST)
    if request.method == "POST":
        # Ensure username was submitted
        if not request.form.get("username"):
            return apology("must provide username", 403)

        # Ensure password was submitted
        elif not request.form.get("password"):
            return apology("must provide password", 403)

        # Query database for username
        rows = db.execute(
            "SELECT * FROM users WHERE username = ?", request.form.get("username")
        )

        # Ensure username exists and password is correct
        if len(rows) != 1 or not check_password_hash(
            rows[0]["hash"], request.form.get("password")
        ):
            return apology("invalid username and/or password", 403)

        # Remember which user has logged in
        session["user_id"] = rows[0]["id"]

        # Redirect user to home page
        return redirect("/")

    # User reached route via GET (as by clicking a link or via redirect)
    else:
        return render_template("login.html")


@app.route("/logout")
def logout():
    """Log user out"""

    # Forget any user_id
    session.clear()

    # Redirect user to login form
    return redirect("/")


@app.route("/quote", methods=["GET", "POST"])
@login_required
def quote():
    if request.method == "POST":
        symbol = request.form.get("symbol")
        if not symbol:
            return apology("must provide symbol", 400)
        quote = lookup(symbol)
        if not quote:
            return apology("invalid symbol", 400)
        # lookup returns dict: { "name":..., "price":..., "symbol":... }
        return render_template("quoted.html", quote=quote)
    else:
        return render_template("quote.html")


# (likely already imported; ensure generate_password_hash is present)


@app.route("/register", methods=["GET", "POST"])
def register():
    """Register user"""
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        confirmation = request.form.get("confirmation")

        if not username:
            return apology("must provide username", 400)
        if not password:
            return apology("must provide password", 400)
        if password != confirmation:
            return apology("passwords do not match", 400)

        hash_ = generate_password_hash(password)
        try:
            db.execute("INSERT INTO users (username, hash) VALUES(?, ?)", username, hash_)
        except ValueError:
            return apology("username already exists", 400)

        # log user in
        rows = db.execute("SELECT id FROM users WHERE username = ?", username)
        session["user_id"] = rows[0]["id"]
        return redirect("/")
    else:
        return render_template("register.html")


@app.route("/sell", methods=["GET", "POST"])
@login_required
def sell():
    if request.method == "POST":
        symbol = request.form.get("symbol")
        shares = request.form.get("shares")

        if not symbol:
            return apology("must select symbol", 400)
        if not shares or not shares.isdigit() or int(shares) <= 0:
            return apology("shares must be positive integer", 400)
        shares = int(shares)

        row = db.execute("SELECT SUM(shares) AS shares FROM transactions WHERE user_id = ? AND symbol = ? GROUP BY symbol",
                         session["user_id"], symbol)
        if not row or row[0]["shares"] is None:
            return apology("you don't own any shares of that stock", 400)

        owned = row[0]["shares"]
        if shares > owned:
            return apology("not enough shares to sell", 400)

        quote = lookup(symbol)
        price = quote["price"]

        # record negative shares
        db.execute("INSERT INTO transactions (user_id, symbol, shares, price) VALUES (?, ?, ?, ?)",
                   session["user_id"], symbol, -shares, price)

        # update cash
        cashrow = db.execute("SELECT cash FROM users WHERE id = ?", session["user_id"])[0]
        newcash = cashrow["cash"] + shares * price
        db.execute("UPDATE users SET cash = ? WHERE id = ?", newcash, session["user_id"])

        return redirect("/")
    else:
        # populate the select with symbols the user owns
        rows = db.execute(
            "SELECT symbol, SUM(shares) as shares FROM transactions WHERE user_id = ? GROUP BY symbol HAVING shares > 0",
            session["user_id"]
        )
        symbols = [r["symbol"] for r in rows]
        return render_template("sell.html", symbols=symbols)


@app.route("/change_password", methods=["GET", "POST"])
@login_required
def change_password():
    if request.method == "POST":
        old = request.form.get("old")
        new = request.form.get("new")
        conf = request.form.get("confirmation")
        if not old or not new:
            return apology("must provide old and new passwords", 400)
        if new != conf:
            return apology("new passwords do not match", 400)

        row = db.execute("SELECT hash FROM users WHERE id = ?", session["user_id"])[0]
        if not check_password_hash(row["hash"], old):
            return apology("old password incorrect", 400)

        db.execute("UPDATE users SET hash = ? WHERE id = ?",
                   generate_password_hash(new), session["user_id"])
        flash("Password changed")
        return redirect("/")
    else:
        return render_template("change_password.html")


@app.route("/add_cash", methods=["GET", "POST"])
@login_required
def add_cash():
    if request.method == "POST":
        amount = request.form.get("amount")
        try:
            value = float(amount)
        except:
            return apology("invalid amount", 400)
        if value <= 0:
            return apology("amount must be positive", 400)

        row = db.execute("SELECT cash FROM users WHERE id = ?", session["user_id"])[0]
        db.execute("UPDATE users SET cash = ? WHERE id = ?",
                   row["cash"] + value, session["user_id"])
        flash("Cash added")
        return redirect("/")
    else:
        return render_template("add_cash.html")
