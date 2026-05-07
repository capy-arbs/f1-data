"""Head-to-Head — compare any two current-grid drivers."""

from db.schema import init_db
from queries.drivers import get_current_drivers
from views.head_to_head import render

init_db()

render(
    drivers=get_current_drivers(),
    title="Head-to-Head Comparison",
    caption="Current grid only. For all-time matchups across eras, see **Records & History → Historical Head-to-Head**.",
)
