# Office parking reservations

Employees reserve a parking slot at an office for a time window, for themselves or for a visitor.
Security checks vehicles in and out with the booking's QR code, the booking code, or the vehicle number.
There are no prices or payments: this is for an organisation's own car parks.

## Who does what

| Role | Can |
|---|---|
| **Employee** (`EMPLOYEE`) | Book slots for themselves and visitors, change / cancel their bookings, manage their vehicles and profile. Sees only the booking screens (`/park`), never the console. |
| **Security Operator** | Everything an employee can, plus the **Security Desk** (scan / look up, check in, check out) and the day's **Slot Bookings**. |
| **Parking Manager / Super Admin** | Everything above, plus **Offices & Slots** (offices, floors, zones, slots, assigned slots), cancelling anyone's booking, and the booking rules in **Settings**. |
| **Report Viewer** | Can book for themselves. |

## Setting up an office

1. **Console → Setup → Offices & Slots → Add office.** Name, city, address, location (click the map), opening hours (or 24 hours).
2. **Add floor** (e.g. *Basement 1*, level −1) and **Zone** (e.g. *A*).
3. **Slots** in a zone: prefix `A-`, first number `1`, how many `20` creates A-01 … A-20. Mark them as EV charger, accessible, or visitors-only, and choose the vehicle type (car, two-wheeler, commercial).
4. Click a slot to edit it, take it **out of service**, move it to another zone, or **assign it permanently** to one person (nobody else can book it; the system gives it to its owner automatically).

## Employee accounts

* An administrator creates them under **Users** with the role *Employee*, or
* employees register themselves at `/register` when **Settings → employee signup domains** lists the company's email domains (for example `company.com`). Other addresses are refused.

Employees then add their vehicles (**Vehicles**). A vehicle number can belong to only one person.

## Booking rules (Settings)

| Setting | Default | Meaning |
|---|---|---|
| `booking_max_days_ahead` | 14 | How far ahead employees can book (managers are not limited) |
| `booking_max_per_day` | 1 | Own bookings per employee per day (visitor bookings not counted) |
| `booking_min_minutes` / `booking_max_hours` | 30 / 14 | Shortest / longest booking |
| `booking_no_show_minutes` | 30 | Not checked in this long after the start: the booking becomes **No-show** and the slot is free again |
| `booking_checkin_early_minutes` | 60 | How early before the start security can check a vehicle in |
| `visitor_bookings_enabled` | true | Employees may book for visitors |
| `employee_signup_domains` | empty | Company email domains allowed to self-register |

Always enforced: the window must be inside the office's parking hours (unless 24 hours); one vehicle cannot have two bookings at the same time; a slot holds one booking at a time.

**No double booking.** Each booking takes the slot row lock and checks for overlap, and PostgreSQL additionally has an exclusion constraint (`ex_booking_no_overlap`, migration 0004) so two overlapping CONFIRMED / CHECKED_IN bookings of one slot are impossible even across servers. Adjacent bookings (09:00–12:00 and 12:00–15:00) are fine.

**Automatic slot choice.** Without a chosen slot, the system picks: the person's assigned slot first; for visitors, a visitor slot; it avoids EV chargers and accessible slots unless they were asked for.

## The QR code

The QR code contains `OPB1:<booking code>:<secret>`. The secret is random per booking, so a QR code cannot be made up from a booking code. Security can also type the 8-character booking code or the vehicle number.

## Security Desk

`/security` (tablet or phone at the gate):

* **Scan QR code** uses the device camera (Chrome / Edge / Android; the page must be opened over HTTPS or on the same computer). Otherwise type the booking code or vehicle number.
* The result says what to do: **Check in** (valid now), **Check out** (parked), or why not (too early, ended, cancelled, another office).
* **Today** lists arriving and parked vehicles with one-tap check-in / check-out; **Slots right now** shows the office's live slot map with vehicle numbers.

Overstays (still checked in 15 minutes after the end) raise one alert per booking in **Alerts**.

## Slot colours

| Colour | Meaning |
|---|---|
| Green | Free |
| Navy | Your booking |
| Amber | Reserved by someone |
| Red | Occupied (checked in) |
| Grey | Assigned to someone / out of service |

Icons: battery = EV charger, wheelchair = accessible, person = visitors only.

## Not included yet

Camera (ANPR) check-in for bookings, email / SMS notifications, and IoT slot sensors are planned next phases. The ANPR gate counting works as before and is independent of bookings.
