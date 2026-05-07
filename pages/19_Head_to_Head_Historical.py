"""Historical Head-to-Head — compare any two drivers across all eras."""

from db.schema import init_db
from queries.drivers import get_all_drivers
from views.head_to_head import render

init_db()

render(
    drivers=get_all_drivers(),
    title="Historical Head-to-Head",
    caption="Compare any two drivers across all loaded seasons. For only the current grid, use **Drivers → Head-to-Head**.",
)
