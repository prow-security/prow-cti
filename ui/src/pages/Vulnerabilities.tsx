import { useState } from "react";
import { ObjectDetail } from "../components/ObjectDetail";
import { ObjectTable } from "../components/ObjectTable";
import { SearchBar } from "../components/SearchBar";

export function VulnerabilitiesPage() {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");

  return (
    <div className="browse-page">
      <header className="browse-page__head">
        <h1 className="browse-page__title">Vulnerabilities</h1>
      </header>
      <div className="browse-page__search">
        <SearchBar onSubmit={setSearchQuery} />
      </div>
      <div className={`browse-split${selectedId ? " browse-split--detail" : ""}`}>
        <div className="browse-split__table">
          <ObjectTable
            searchQuery={searchQuery}
            selectedId={selectedId}
            onSelect={setSelectedId}
            objectType="vulnerability"
          />
        </div>
        {selectedId ? (
          <aside className="browse-split__detail">
            <ObjectDetail selectedId={selectedId} onClose={() => setSelectedId(null)} />
          </aside>
        ) : null}
      </div>
    </div>
  );
}
