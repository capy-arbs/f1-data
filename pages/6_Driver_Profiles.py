"""Driver Profiles — full career summary for any current-grid driver."""

from db.schema import init_db
from queries.drivers import get_current_drivers
from views.driver_profile import render

init_db()

render(
    drivers=get_current_drivers(),
    title="Driver Profiles",
    caption="Drivers active in the current season. For retired drivers and full archive, see **Records & History → Historical Driver Profiles**.",
)
