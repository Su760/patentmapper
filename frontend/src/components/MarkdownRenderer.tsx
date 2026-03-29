"use client";

import React from "react";

interface MarkdownRendererProps {
  content: string;
  className?: string;
}

function renderInline(text: string): React.ReactNode[] {
  const parts = text.split(
    /(\*\*[^*]+\*\*|\[[^\]]+\]\(https?:\/\/[^)]+\)|\[[^\]]+\])/g
  );
  return parts.map((part, i) => {
    if (part.startsWith("**") && part.endsWith("**")) {
      return (
        <strong key={i} className="text-white font-semibold">
          {part.slice(2, -2)}
        </strong>
      );
    }
    const linkMatch = part.match(/^\[([^\]]+)\]\((https?:\/\/[^)]+)\)$/);
    if (linkMatch) {
      return (
        <a
          key={i}
          href={linkMatch[2]}
          target="_blank"
          rel="noopener noreferrer"
          className="text-blue-400 hover:text-blue-300 underline"
        >
          {linkMatch[1]}
        </a>
      );
    }
    if (part.startsWith("[") && part.endsWith("]")) {
      return (
        <span key={i} className="text-blue-400 font-mono text-sm">
          {part}
        </span>
      );
    }
    return <React.Fragment key={i}>{part}</React.Fragment>;
  });
}

export default function MarkdownRenderer({
  content,
  className = "",
}: MarkdownRendererProps) {
  const lines = content.split("\n");
  const elements: React.ReactNode[] = [];

  lines.forEach((line, i) => {
    if (line.startsWith("# ")) {
      elements.push(
        <h1 key={i} className="text-2xl font-bold text-white mt-8 mb-4">
          {renderInline(line.slice(2))}
        </h1>
      );
    } else if (line.startsWith("## ")) {
      elements.push(
        <h2
          key={i}
          className="text-xl font-bold text-white mt-6 mb-3 border-b border-gray-700 pb-2"
        >
          {renderInline(line.slice(3))}
        </h2>
      );
    } else if (line.startsWith("### ")) {
      elements.push(
        <h3 key={i} className="text-lg font-semibold text-blue-300 mt-5 mb-2">
          {renderInline(line.slice(4))}
        </h3>
      );
    } else if (line.startsWith("> ")) {
      elements.push(
        <blockquote
          key={i}
          className="border-l-4 border-blue-500 pl-4 text-gray-300 italic my-3"
        >
          {renderInline(line.slice(2))}
        </blockquote>
      );
    } else if (line.trim() === "---") {
      elements.push(<hr key={i} className="border-gray-700 my-6" />);
    } else if (/^\d+\.\s/.test(line)) {
      elements.push(
        <li
          key={i}
          className="text-gray-300 ml-4 list-decimal list-inside mb-1"
        >
          {renderInline(line.replace(/^\d+\.\s/, ""))}
        </li>
      );
    } else if (line.startsWith("- ") || line.startsWith("* ")) {
      elements.push(
        <li key={i} className="text-gray-300 ml-4 list-disc list-inside mb-1">
          {renderInline(line.slice(2))}
        </li>
      );
    } else if (line.trim() === "") {
      elements.push(<div key={i} className="h-2" />);
    } else {
      elements.push(
        <p key={i} className="text-gray-300 leading-relaxed mb-2">
          {renderInline(line)}
        </p>
      );
    }
  });

  return <div className={className}>{elements}</div>;
}
