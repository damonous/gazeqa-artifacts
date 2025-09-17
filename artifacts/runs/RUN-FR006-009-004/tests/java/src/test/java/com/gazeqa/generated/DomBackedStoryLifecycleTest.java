package com.gazeqa.generated;

import static org.junit.jupiter.api.Assertions.assertTrue;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.stream.Collectors;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;

@DisplayName("DOM-backed story lifecycle checks")
class DomBackedStoryLifecycleTest {
  private static final Path RUN_ROOT = Path.of(".").toAbsolutePath().normalize();
  private static final Path STORIES_JSON = RUN_ROOT.resolve("../../frd/stories_export.json").normalize();
  private static final Path DOM_DIR = RUN_ROOT.resolve("../../source/dom").normalize();

  private List<Map<String, Object>> loadStories() throws IOException {
    ObjectMapper mapper = new ObjectMapper();
    Map<String, Object> payload = mapper.readValue(
        Files.newBufferedReader(STORIES_JSON), new TypeReference<>() {});
    Object features = payload.get("features");
    if (!(features instanceof List<?> list)) {
      throw new IllegalStateException("features list missing");
    }
    @SuppressWarnings("unchecked")
    List<Map<String, Object>> typed = (List<Map<String, Object>>) list;
    return typed;
  }

  @Test
  @DisplayName("About/Team/Admin stories exported")
  void aboutTeamAdminStories() throws IOException {
    Set<String> stories = loadStories().stream()
        .map(item -> (String) item.get("story_id"))
        .collect(Collectors.toSet());
    assertTrue(stories.contains("STORY-FR-006-ABOUT"));
    assertTrue(stories.contains("STORY-FR-006-TEAM"));
    assertTrue(stories.contains("STORY-FR-006-ADMIN"));
  }

  @Test
  @DisplayName("Admin DOM includes audit table")
  void adminDomIncludesAuditTable() throws IOException {
    String html = Files.readString(DOM_DIR.resolve("admin.html"));
    assertTrue(html.contains("table class=\"audit\""));
    assertTrue(html.contains("<th>User</th>"));
  }
}
