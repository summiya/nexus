import { useMemo, useState } from "react";
import { Link, NavLink } from "react-router-dom";

import { useConversationsQuery } from "./queries";

function conversationTitle(title: string | null): string {
  return title ?? "New conversation";
}

export function ConversationSidebar() {
  const conversations = useConversationsQuery();
  const items = conversations.data ?? [];
  const [search, setSearch] = useState("");

  const filteredItems = useMemo(() => {
    const query = search.trim().toLocaleLowerCase();
    if (!query) {
      return items;
    }
    return items.filter((item) =>
      conversationTitle(item.title).toLocaleLowerCase().includes(query),
    );
  }, [items, search]);

  return (
    <aside
      className="conversation-sidebar"
      aria-labelledby="conversation-sidebar-title"
    >
      <div className="conversation-sidebar-header">
        <span className="conversation-sidebar-eyebrow">YOUR WORKSPACE</span>
        <div className="conversation-sidebar-title-row">
          <h1 id="conversation-sidebar-title">Conversations</h1>
          <span className="conversation-sidebar-title-icon" aria-hidden="true">
            ✧
          </span>
        </div>
        <NavLink
          className={({ isActive }) =>
            "new-chat-link" + (isActive ? " active" : "")
          }
          end
          to="/conversations"
        >
          <span aria-hidden="true">＋</span> New chat
          <span className="conversation-new-chat-arrow" aria-hidden="true">
            ↗
          </span>
        </NavLink>
        <div className="conversation-search">
          <label htmlFor="conversation-history-search">
            <span className="conversation-search-icon" aria-hidden="true">
              ⌕
            </span>
            <span className="conversation-visually-hidden">
              Search conversations
            </span>
          </label>
          <input
            id="conversation-history-search"
            aria-label="Search conversations"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search recent conversations"
            type="search"
          />
        </div>
      </div>

      <div className="conversation-sidebar-content">
        <div className="conversation-list-heading">
          <span>RECENT CONVERSATIONS</span>
          {!conversations.isPending && !conversations.isError ? (
            <span>{filteredItems.length}</span>
          ) : null}
        </div>
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
        ) : filteredItems.length === 0 ? (
          <p className="conversation-list-status">
            No conversations match your search.
          </p>
        ) : (
          <nav aria-label="Conversation list">
            <ul className="conversation-list">
              {filteredItems.map((conversation) => (
                <li key={conversation.publicId}>
                  <NavLink
                    className={({ isActive }) =>
                      "conversation-list-link" + (isActive ? " active" : "")
                    }
                    end
                    to={"/conversations/" + conversation.publicId}
                  >
                    <span aria-hidden="true" className="conversation-list-symbol" />
                    <span className="conversation-list-title">
                      {conversationTitle(conversation.title)}
                    </span>
                  </NavLink>
                </li>
              ))}
            </ul>
          </nav>
        )}
      </div>

      <div className="conversation-sidebar-shortcuts">
        <div className="conversation-list-heading">
          <span>QUICK ACCESS</span>
        </div>
        <nav aria-label="Workspace shortcuts">
          <Link to="/files">
            <span aria-hidden="true">▤</span> Files
            <span aria-hidden="true" className="conversation-shortcut-arrow">
              ↗
            </span>
          </Link>
          <Link to="/settings/ai-models">
            <span aria-hidden="true">◈</span> AI models
            <span aria-hidden="true" className="conversation-shortcut-arrow">
              ↗
            </span>
          </Link>
          <Link to="/explore">
            <span aria-hidden="true">⌁</span> Explore NEXUS
            <span aria-hidden="true" className="conversation-shortcut-arrow">
              ↗
            </span>
          </Link>
        </nav>
        <div className="conversation-sidebar-footer">
          <span className="conversation-org-avatar" aria-hidden="true">
            N
          </span>
          <span>
            <strong>Your organization</strong>
            <small>Protected workspace</small>
          </span>
          <span aria-hidden="true">◇</span>
        </div>
      </div>
    </aside>
  );
}
