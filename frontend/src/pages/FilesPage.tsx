import { FileLibrary, FileUploadPanel } from "../features/files";

export function FilesPage() {
  return (
    <section className="files-page">
      <FileUploadPanel />
      <FileLibrary />
    </section>
  );
}
