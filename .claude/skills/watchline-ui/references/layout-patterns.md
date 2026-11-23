# Layout patterns

Page: `st.set_page_config(layout="wide")`. Keep the title short ("Watchline NYC").

## Brand banner
A navy card with a 4px gold left border, rounded 10px, padding about 1rem 1.2rem. Inside: a tagline in small
uppercase gold ("Accountability infrastructure for NYC housing") over the title in white, 1.7rem, bold.

## Sidebar
Navy. Logo first (`assets/logo.png`, full width, rounded 12px, centered, tucked up under the top edge).
Then, in order: sample questions, then a "New chat" button that resets the conversation. Keep it thin.

## Chat
Standard Streamlit chat: `st.chat_input` ("Ask about a building, landlord, or portfolio"), user and assistant
messages, answer streamed. Under each assistant answer: the Evidence expander (see `answer-rendering.md`).

## Side panel for larger outputs
Reports, long tables and network views open beside the chat in a panel with a header (title, expand, close).
The panel can expand to full width. Render raw HTML in an isolated iframe so its CSS cannot touch the app.

## Chips
Rounded pills (`border-radius: 999px`), navy-2 background, white text, thin gold border, the number in gold
bold. Use for counts such as "Open violations 12". Show at most 8, then "+N more".

## Tables
`st.dataframe` with hidden index. Counts as proportional bars (`ProgressColumn`). Single-row selection where a
row drives another view. A caption underneath says what selecting does.

## Empty and error states
Say what is missing and why in one plain sentence ("No violations recorded for this building."). Never show
a stack trace. A missing record is not a clean bill: say "none recorded", not "none".
