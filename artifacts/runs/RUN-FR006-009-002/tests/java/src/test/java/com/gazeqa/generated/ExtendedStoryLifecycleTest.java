package com.gazeqa.generated;

import static org.junit.jupiter.api.Assertions.assertEquals;
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

@DisplayName("Extended story lifecycle coverage")
class ExtendedStoryLifecycleTest {
  private static final Path RUN_ROOT = Path.of(".").toAbsolutePath().normalize();
  private static final Path STORIES_JSON = RUN_ROOT.resolve("../../frd/stories_export.json").normalize();

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
  @DisplayName("Story catalog includes new clusters")
  void storyCatalogIncludesNewClusters() throws IOException {
    Set<String> stories = loadStories().stream()
        .map(item -> (String) item.get("story_id"))
        .collect(Collectors.toSet());
    assertTrue(stories.contains("STORY-FR-006-REPORTS"));
    assertTrue(stories.contains("STORY-FR-006-SETTINGS"));
    assertTrue(stories.contains("STORY-FR-006-USERS"));
  }

  @Test
  @DisplayName("Acceptance criteria counts align with evidence")
  void acceptanceCriteriaCountsAlign() throws IOException {
    Map<String, Long> counts = loadStories().stream()
        .collect(Collectors.toMap(
            item -> (String) item.get("story_id"),
            item -> {
              Object criteria = item.get("acceptance_criteria");
              if (criteria instanceof List<?> list) {
                return (long) list.size();
              }
              return 0L;
            }));
    assertEquals(2L, counts.get("STORY-FR-006-REPORTS"));
    assertEquals(2L, counts.get("STORY-FR-006-SETTINGS"));
    assertEquals(2L, counts.get("STORY-FR-006-USERS"));
  }
}
