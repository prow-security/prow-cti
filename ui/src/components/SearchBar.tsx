import { useCallback, useState } from "react";

export interface SearchBarProps {
  onSubmit: (query: string) => void;
}

export function SearchBar({ onSubmit }: SearchBarProps) {
  const [draft, setDraft] = useState("");

  const submit = useCallback(() => {
    onSubmit(draft.trim());
  }, [draft, onSubmit]);

  const clear = useCallback(() => {
    setDraft("");
    onSubmit("");
  }, [onSubmit]);

  return (
    <div className="search-bar">
      <div className="search-bar__input-wrap">
        <input
          className="search-bar__input"
          type="search"
          placeholder="Search STIX objects…"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              submit();
            }
          }}
          aria-label="Search STIX objects"
        />
        {draft ? (
          <button type="button" className="search-bar__clear" onClick={clear} aria-label="Clear search">
            ×
          </button>
        ) : null}
      </div>
      <button type="button" className="search-bar__submit" onClick={submit}>
        Search
      </button>
    </div>
  );
}
