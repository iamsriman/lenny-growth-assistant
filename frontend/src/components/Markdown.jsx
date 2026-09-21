import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

// Markdown is rendered from the AST only. `rehype-raw` is deliberately NOT
// installed, so any HTML that survives into a Markdown artifact is printed as
// text rather than parsed — one fewer way for model output to become markup.
const components = {
  table: ({ node, ...props }) => (
    <div className="tablewrap">
      <table {...props} />
    </div>
  ),
  a: ({ node, href, ...props }) => (
    <a href={href} target="_blank" rel="noopener noreferrer nofollow" {...props} />
  ),
};

export default function Markdown({ children }) {
  return (
    <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
      {children || ""}
    </ReactMarkdown>
  );
}
