import { NavLink } from "react-router-dom";

import { useConversationsQuery } from "../../features/conversations/queries";
import type { ConversationSummary } from "../../features/conversations/types";
import { DashboardIcon } from "./DashboardIcon";

function newestFirst(
  items: readonly ConversationSummary[],
): ConversationSummary[] {
  return [...items].sort(
    (left, right) => Date.parse(right.updatedAt) - Date.parse(left.updatedAt),
  );
}

export function RecentConversationsMenu({
  closeSidebar,
}: {
  closeSidebar: () => void;
}) {
  const conversations = useConversationsQuery();
  const items = newestFirst(conversations.data ?? []);

  return (
    <section className="nx-dash-recents" aria-label="Recent conversations">
      <NavLink
        to="/conversations"
        end
        className={({ isActive }) =>
          "nx-dash-new-chat" + (isActive ? " active" : "")
        }
        onClick={closeSidebar}
      >
        <span aria-hidden="true">＋</span>
        New chat
        <DashboardIcon name="arrow" size={14} />
      </NavLink>

      <div className="nx-dash-recents-heading">
        <span>RECENT CHATS</span>
        {conversations.isSuccess ? <span>{items.length}</span> : null}
      </div>

      {conversations.isPending ? (
        <p className="nx-dash-recents-state" role="status">
          Loading recent chats…
        </p>
      ) : conversations.isError ? (
        <div className="nx-dash-recents-state">
          <p role="alert">Chats are temporarily unavailable.</p>
          <button
            type="button"
            disabled={conversations.isFetching}
            onClick={() => void conversations.refetch()}
          >
            {conversations.isFetching ? "Retrying…" : "Retry"}
          </button>
        </div>
      ) : items.length === 0 ? (
        <p className="nx-dash-recents-state">No conversations yet.</p>
      ) : (
        <nav className="nx-dash-recents-scroll" aria-label="Recent chat list">
          {items.map((conversation) => (
            <NavLink
              key={conversation.publicId}
              to={"/conversations/" + encodeURIComponent(conversation.publicId)}
              onClick={closeSidebar}
              className={({ isActive }) =>
                "nx-dash-recent-chat" + (isActive ? " active" : "")
              }
              title={conversation.title ?? "New conversation"}
            >
              <span aria-hidden="true" className="nx-dash-recent-chat-icon">
                ◫
              </span>
              <span className="nx-dash-recent-chat-title">
                {conversation.title ?? "New conversation"}
              </span>
            </NavLink>
          ))}
        </nav>
      )}
    </section>
  );
}
