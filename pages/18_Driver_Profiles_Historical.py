"""Historical Driver Profiles — full archive of every driver in the database."""

from db.schema import init_db
from queries.drivers import get_all_drivers
from views.driver_profile import render

init_db()

render(
    drivers=get_all_drivers(),
    title="Historical Driver Profiles",
    caption="Every driver in the database, 1950 to present. For just the current grid, use **Drivers → Driver Profiles**.",
)
