import { NavLink } from "react-router-dom";

import { useConversationsQuery } from "./queries";

function conversationTitle(title: string | null): string {
  return title ?? "New conversation";
}

export function ConversationSidebar() {
  const conversations = useConversationsQuery();
  const items = conversations.data ?? [];

  return (
    <aside
      className="conversation-sidebar"
      aria-labelledby="conversation-sidebar-title"
    >
      <div className="conversation-sidebar-header">
        <h1 id="conversation-sidebar-title">Conversations</h1>
        <NavLink
          className={({ isActive }) =>
            `new-chat-link${isActive ? " active" : ""}`
          }
          end
          to="/conversations"
        >
          <span aria-hidden="true">+</span> New chat
        </NavLink>
      </div>

      <div className="conversation-sidebar-content">
        {conversations.isPending ? (
          <p className="conversation-list-status" role="status">
            Loading conversations…
          </p>
        ) : conversations.isError ? (
          <div className="conversation-list-error">
            <p role="alert">Conversations are temporarily unavailable.</p>
            <button
              className="text-button"
              disabled={conversations.isFetching}
              type="button"
              onClick={() => void conversations.refetch()}
            >
              {conversations.isFetching ? "Retrying…" : "Retry"}
            </button>
          </div>
        ) : items.length === 0 ? (
          <p className="conversation-list-status">No conversations yet.</p>
        ) : (
          <nav aria-label="Conversation list">
            <ul className="conversation-list">
              {items.map((conversation) => (
                <li key={conversation.publicId}>
                  <NavLink
                    className={({ isActive }) =>
                      `conversation-list-link${isActive ? " active" : ""}`
                    }
                    end
                    to={`/conversations/${conversation.publicId}`}
                  >
                    {conversationTitle(conversation.title)}
                  </NavLink>
                </li>
              ))}
            </ul>
          </nav>
        )}
      </div>
    </aside>
  );
}
