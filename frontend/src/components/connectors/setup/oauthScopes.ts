export type OAuthScope = {
  scope: string;
  required: boolean;
  description: string;
};

export const CONFLUENCE_SCOPES: OAuthScope[] = [
  {
    scope: "read:confluence-content.all",
    required: true,
    description: "Read pages, blog posts, and attachments",
  },
  {
    scope: "read:confluence-space.summary",
    required: false,
    description: "List accessible spaces",
  },
  {
    scope: "offline_access",
    required: false,
    description: "Refresh access tokens without re-authentication",
  },
];

export const GOOGLE_DRIVE_SCOPES: OAuthScope[] = [
  {
    scope: "https://www.googleapis.com/auth/drive.readonly",
    required: true,
    description: "Read files, folders, and metadata",
  },
  {
    scope: "https://www.googleapis.com/auth/drive.metadata.readonly",
    required: false,
    description: "Read file metadata without downloading content",
  },
];

export const MICROSOFT_SHAREPOINT_ONEDRIVE_SCOPES: OAuthScope[] = [
  {
    scope: "offline_access",
    required: true,
    description: "Refresh access without reauthorizing the app",
  },
  {
    scope: "Files.Read.All",
    required: true,
    description: "Read OneDrive files and document library content",
  },
  {
    scope: "Sites.Read.All",
    required: true,
    description: "Discover SharePoint sites and libraries",
  },
  {
    scope: "User.Read",
    required: false,
    description: "Validate the signed-in Microsoft account",
  },
];
