# Plume — artful gothic, first direction

Branch: `design/gothic-plume-v1`

An independent salon collective with the feel of an antique art print: bone paper,
charcoal ink, oxblood, dramatic editorial type, a slightly crooked poster, and an
original moth / moon / scissors illustration. The voice is warm, strange, and welcoming.

The homepage, booking page, operator login, and dashboard share the same design.
Layouts adapt to phones; forms retain native labels, keyboard focus, and ordinary
HTML submission. Reduced-motion preferences disable motion effects.

## Revision map

- `plume/web/templates/styles.css`: color and typography tokens at the top;
  page styles and responsive breakpoints below.
- `plume/web/templates/illustrations.html`: reusable original SVG illustrations.
- `plume/web/templates/index.html`: homepage content and section composition.
- `plume/web/templates/base.html`: shared navigation, fonts, and footer.
- The other page templates retain existing endpoints and server-rendered workflows.

Google Fonts supplies Bodoni Moda and DM Sans, with local serif/sans-serif fallbacks.
HTMX is pinned to 2.0.8; ordinary form submissions also work without JavaScript.
The booking form selects only the availability section from HTMX responses and
excludes inactive profiles, matching the reservation service's eligibility rules.

The private-studio card describes the concept without inventing a booking or inquiry
flow. Community copy presents art and music as the vision, without invented events,
prices, testimonials, or a confirmed street address.
